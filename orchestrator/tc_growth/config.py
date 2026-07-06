"""Central configuration, site profiles, and KPI definitions (provider-neutral).

Multi-site profiles: the same codebase runs against staging, production, or any other WordPress
site. `TC_SITE` (env var or `--site` CLI flag) selects `orchestrator/profiles/<site>.env`; unset
falls back to the classic `orchestrator/.env` — existing deployments keep working unchanged.
Profiles are COMPLETE per site (separate credentials, signing keys, store) — never shared across
sites — and one process serves exactly one site (TC_SITE is read at load time).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Release identity — matches the ladder in docs/STATUS.md; shown with the commit on the dashboard.
RELEASE = "0.3"

# Anchor: the orchestrator/ directory (next to pyproject.toml), independent of the CWD so
# everything also works under systemd.
BASE_DIR = Path(__file__).resolve().parents[1]
# Classic single-site env file — the fallback when no TC_SITE profile is selected.
ENV_PATH = BASE_DIR / ".env"


def active_site() -> str:
    """The selected site profile name ('' = classic single-site .env mode)."""
    return os.environ.get("TC_SITE", "").strip()


def resolved_env_path() -> Path:
    """Which env file this process runs against: profiles/<site>.env, or .env when no site set."""
    site = active_site()
    if site:
        return BASE_DIR / "profiles" / f"{site}.env"
    return ENV_PATH


def load_env() -> None:
    """Load the resolved env file into the PROCESS environment.

    Third-party SDKs (the Anthropic client) and os.environ lookups read the process environment,
    and pydantic does NOT export to it — so this must run before anything else. `override=False`
    keeps real environment variables (e.g. injected by systemd) authoritative over the file.
    An unknown TC_SITE fails LOUDLY — silently falling back to another site's credentials is the
    one mistake this system must never make.
    """
    path = resolved_env_path()
    if active_site() and not path.exists():
        raise SystemExit(f"Unknown site profile '{active_site()}': {path} not found. "
                         f"Create it (see profiles/*.env.example) or unset TC_SITE.")
    load_dotenv(path, override=False)


class Settings(BaseSettings):
    """Environment-driven settings. Secrets come from the environment / a vault, never code.

    Reads the PROCESS environment only — get_settings() runs load_env() first, which exports the
    resolved env file (profile or classic .env). This keeps profile selection in exactly one place.
    """

    model_config = SettingsConfigDict(env_prefix="TC_", extra="ignore")

    # --- Site identity (multi-site profiles) ---
    site_name: str = Field(default="", description="Human label, e.g. 'Tossa Cycling Staging'")
    env_kind: str = Field(default="staging", description="staging | production — shown on every surface")
    allow_writes: bool = Field(default=True, description="False = profile-level cap: every run is clamped read-only regardless of requested phase (production default)")

    # --- WordPress connector ---
    wp_base_url: str = Field(default="", description="e.g. https://tossacycling.com")
    wp_user: str = Field(default="", description="Dedicated agent WordPress user login")
    wp_app_password: str = Field(default="", description="WordPress Application Password")
    wp_signing_key: str = Field(default="", description="Shared HMAC key (matches plugin)")

    # --- Google ---
    gsc_site_url: str = Field(default="", description="Search Console property, e.g. sc-domain:tossacycling.com")
    ga4_property_id: str = Field(default="", description="GA4 numeric property id")
    google_ads_customer_id: str = Field(default="", description="Google Ads customer id (no dashes)")
    pagespeed_api_key: str = Field(default="", description="PageSpeed Insights API key")

    # --- Meta ---
    meta_ad_account_id: str = Field(default="", description="act_<id>")

    # --- AI runtime (only used by runtime/) ---
    ai_provider: str = Field(default="anthropic", description="anthropic | openai | gemini")
    ai_model: str = Field(default="claude-opus-4-8", description="Strong tier: strategy, investigations")
    ai_model_mid: str = Field(default="claude-sonnet-4-6", description="Mid tier: routine reporting")
    ai_model_cheap: str = Field(default="claude-haiku-4-5", description="Cheap tier: monitoring, bulk")
    # Task-kind -> model overrides, as JSON (e.g. TC_MODEL_POLICY='{"weekly-report":"claude-opus-4-8"}').
    # Unknown kinds fall back to ai_model. See model_for().
    model_policy: dict[str, str] = Field(default_factory=dict)

    # --- Persistence (Phase 2) ---
    db_path: str = Field(default="", description="SQLite path; blank = orchestrator/data/tc_growth.db")

    # --- Credentials ---
    secrets_dir: str = Field(default="", description="Credential dir; blank = orchestrator/secrets")

    # --- Reporting ---
    report_channel: str = Field(default="email", description="email | telegram")
    report_recipient: str = Field(default="lukaszkomar@gmail.com")
    report_sender: str = Field(default="", description="From address; defaults to smtp_user")

    # SMTP (email delivery). When unset, delivery falls back to stdout (never raises).
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_starttls: bool = Field(default=True)


# Business KPIs the agent reasons against. Provider-neutral; referenced by core/ and the prompts.
KPIS = {
    "bookings": "Count of completed WooCommerce rental/tour orders.",
    "revenue": "Gross revenue from completed orders, by channel and product.",
    "conversion_rate": "Sessions -> bookings, by landing page and channel.",
    "ctr": "Search Console click-through rate per query/page.",
    "avg_position": "Average Search Console position per query/page.",
    "ad_spend": "Spend per campaign across Google Ads and Meta.",
    "cost_per_booking": "Ad spend / tracked bookings per campaign.",
    "roas": "Revenue attributed / ad spend per campaign.",
}


def get_settings() -> Settings:
    load_env()  # idempotent; ensures the resolved profile is in the environment first
    return Settings()


def writes_allowed() -> bool:
    """Profile-level write cap, read straight from the environment (fast, import-cycle-free).

    core.approval consults this beneath the phase gate: a read-only profile (production default)
    blocks every write tool no matter what phase a run requests.
    """
    return os.environ.get("TC_ALLOW_WRITES", "true").strip().lower() not in ("false", "0", "no")


def site_label(s: Settings | None = None) -> str:
    """Unmistakable site marker for reports, headers, and the dashboard."""
    s = s or get_settings()
    name = s.site_name or (active_site() or "default")
    return f"{name} · {s.env_kind.strip().upper() or 'STAGING'}"


def secrets_path(filename: str) -> Path:
    """Absolute path of a credential file under orchestrator/secrets/, independent of the
    current working directory (same anchoring as ENV_PATH — a CWD-relative secrets path broke
    the Google tools whenever a command was run from outside orchestrator/). TC_SECRETS_DIR
    overrides the directory."""
    base = get_settings().secrets_dir
    return (Path(base).expanduser() if base else BASE_DIR / "secrets") / filename


# Which tier each task kind uses by default. Investigations and strategy stay on the strong
# tier deliberately (forensics is where wrong conclusions are most expensive); routine weekly
# reporting runs on the mid tier. Nothing is on the cheap tier by default — per ROADMAP,
# measure before trusting it ("cheap is only cheap if it's good enough").
_DEFAULT_TIER_FOR_KIND = {
    "weekly-report": "mid",
    "investigate": "strong",
    "draft-test": "mid",     # supervised validation drafts (content work, human-reviewed)
    "monitoring": "cheap",   # future scheduled checks; opt-in kind, nothing uses it yet
}


def model_for(kind: str, settings: Settings | None = None) -> str:
    """Resolve the model for a task kind: explicit TC_MODEL_POLICY entry wins, then the default
    tier map, then the strong tier. Keeps model choice a config concern, not code scattered."""
    s = settings or get_settings()
    if kind in s.model_policy:
        return s.model_policy[kind]
    tier = _DEFAULT_TIER_FOR_KIND.get(kind, "strong")
    return {"strong": s.ai_model, "mid": s.ai_model_mid, "cheap": s.ai_model_cheap}[tier]
