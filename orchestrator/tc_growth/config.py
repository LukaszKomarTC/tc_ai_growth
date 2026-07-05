"""Central configuration and KPI definitions (provider-neutral)."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Canonical .env location: orchestrator/.env (next to pyproject.toml), resolved independently of
# the current working directory so it also works under systemd.
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_env() -> None:
    """Load orchestrator/.env into the PROCESS environment.

    Our Settings read `.env` directly via pydantic, but third-party SDKs (the Anthropic client)
    and a few os.environ lookups (Meta / Telegram tokens) read the OS environment. pydantic does
    NOT export to os.environ, so without this those keys are invisible. `override=False` keeps any
    real environment variables (e.g. injected by systemd) authoritative over the file.
    """
    load_dotenv(ENV_PATH, override=False)


class Settings(BaseSettings):
    """Environment-driven settings. Secrets come from the environment / a vault, never code."""

    model_config = SettingsConfigDict(env_prefix="TC_", env_file=str(ENV_PATH), extra="ignore")

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
    return Settings()


def secrets_path(filename: str) -> Path:
    """Absolute path of a credential file under orchestrator/secrets/, independent of the
    current working directory (same anchoring as ENV_PATH — a CWD-relative secrets path broke
    the Google tools whenever a command was run from outside orchestrator/). TC_SECRETS_DIR
    overrides the directory."""
    base = get_settings().secrets_dir
    return (Path(base).expanduser() if base else ENV_PATH.parent / "secrets") / filename


# Which tier each task kind uses by default. Investigations and strategy stay on the strong
# tier deliberately (forensics is where wrong conclusions are most expensive); routine weekly
# reporting runs on the mid tier. Nothing is on the cheap tier by default — per ROADMAP,
# measure before trusting it ("cheap is only cheap if it's good enough").
_DEFAULT_TIER_FOR_KIND = {
    "weekly-report": "mid",
    "investigate": "strong",
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
