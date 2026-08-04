"""Target-bound approval envelopes (WP-U4) — canonicalization, hashing, validation.

An approval never binds bare payload bytes: it binds the ENVELOPE — schema version, site
profile, environment, kind, target and payload together — so an identical SEO payload approved
for the wrong site or environment is impossible by construction (spec: WP-U4 §Schema).

Canonical serialization is pinned here and only here:

    json.dumps(envelope, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    encoded as UTF-8, hashed with SHA-256.

Stable key order, no insignificant whitespace, real Unicode (no \\uXXXX escapes for non-ASCII),
`schema_version` inside the hashed bytes. The same logical envelope always hashes identically;
any material change — including target or environment — never does. Byte-exact fixtures live in
tests/test_decision_workflow.py; changing this function is a schema change, not a refactor.

Pure stdlib, no store or provider imports — callable from the store layer, the CLI and tests.
"""

from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = "u4/1"

_ENVIRONMENTS = ("staging", "production")
# Exact top-level shape. Unknown keys are refused, not ignored: an ignored key would still be
# hashed (changing the approval binding) while remaining invisible to validation — fail closed.
_REQUIRED_KEYS = frozenset({"schema_version", "profile", "environment", "kind", "target",
                            "payload"})

# Target schemas are CLOSED and per-kind (review #71 finding 2): a kind without a schema here
# cannot be proposed at all, and a target may carry only the exact keys its kind documents —
# an extra key would be hashed into the approval while staying invisible to validation and
# rendering, which is precisely the hole this table closes. Adding a decision kind therefore
# STARTS with adding its schema (and its tests), not with relaxing validation.
_KIND_TARGET_KEYS: dict[str, frozenset[str]] = {
    "seo_meta_update": frozenset({"object_type", "post_id", "expected_urls"}),
}
_KIND_REQUIRED_URL_LANGS: dict[str, frozenset[str]] = {
    # Bilingual site: an SEO meta approval that covers only one language variant is not the
    # change the owner reviewed on a page that serves both.
    "seo_meta_update": frozenset({"es", "en"}),
}


def canonical_json(envelope: dict) -> str:
    """The one canonical text form of an envelope. Every persisted envelope is stored in this
    form, so stored text == hashed text with no re-serialization ambiguity."""
    return json.dumps(envelope, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def envelope_sha256(envelope: dict) -> str:
    return hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()


def _validate_url(url: object, label: str) -> list[str]:
    """A target URL must be well-formed HTTPS with a real host — an approval binding to a URL
    the verifier could never safely fetch is refused at authoring time, not discovered at
    verification time. (Whether the HOST belongs to the profile is context the proposal
    boundary enforces — see store.records.propose_decision.)"""
    from urllib.parse import urlsplit

    if not (isinstance(url, str) and url.strip()):
        return [f"{label} must be a non-empty URL string"]
    try:
        parts = urlsplit(url)
    except ValueError:
        return [f"{label} is not a parseable URL"]
    problems = []
    if parts.scheme != "https":
        problems.append(f"{label} must be https:// (got {parts.scheme or 'no scheme'!r})")
    if not parts.hostname:
        problems.append(f"{label} has no host")
    return problems


def url_host(url: str) -> str | None:
    """Lower-cased host of a URL, or None — the proposal boundary's host-allowlist input."""
    from urllib.parse import urlsplit

    try:
        return (urlsplit(url).hostname or "").lower() or None
    except ValueError:
        return None


def validate_envelope(envelope: object) -> list[str]:
    """Structural validation; returns a list of plain-English problems (empty == valid).

    Shape and vocabulary are fully CLOSED: unknown top-level keys, unknown kinds, unknown
    target keys and missing language variants are all refused — anything hashed must be
    validated and rendered. Whether the kind has an accepted EXECUTION path remains the Action
    Registry's question; whether profile/environment/hosts match the RUNTIME CONTEXT is the
    proposal boundary's question (store.records.propose_decision) — this function has no
    context and must not pretend to."""
    problems: list[str] = []
    if not isinstance(envelope, dict):
        return ["envelope must be a JSON object"]
    missing = _REQUIRED_KEYS - envelope.keys()
    extra = envelope.keys() - _REQUIRED_KEYS
    if missing:
        problems.append(f"missing keys: {', '.join(sorted(missing))}")
    if extra:
        problems.append(f"unknown keys refused (they would be hashed but never validated): "
                        f"{', '.join(sorted(extra))}")
    if envelope.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if envelope.get("environment") not in _ENVIRONMENTS:
        problems.append(f"environment must be one of {'/'.join(_ENVIRONMENTS)}")
    for key in ("profile", "kind"):
        v = envelope.get(key)
        if not (isinstance(v, str) and v.strip()):
            problems.append(f"{key} must be a non-empty string")

    kind = envelope.get("kind")
    target_keys = _KIND_TARGET_KEYS.get(kind) if isinstance(kind, str) else None
    if isinstance(kind, str) and kind.strip() and target_keys is None:
        problems.append(f"unknown kind {kind!r} — a decision kind must have a defined target "
                        "schema before it can be proposed")

    target = envelope.get("target")
    if not isinstance(target, dict):
        problems.append("target must be an object")
    elif target_keys is not None:
        t_missing = target_keys - target.keys()
        t_extra = target.keys() - target_keys
        if t_missing:
            problems.append(f"target missing keys: {', '.join(sorted(t_missing))}")
        if t_extra:
            problems.append("unknown target keys refused (hashed but never validated): "
                            + ", ".join(sorted(str(k) for k in t_extra)))
        if kind == "seo_meta_update":
            if target.get("object_type") != "wp_post":
                problems.append("target.object_type must be 'wp_post' for seo_meta_update")
            post_id = target.get("post_id")
            if not (isinstance(post_id, int) and not isinstance(post_id, bool) and post_id > 0):
                problems.append("target.post_id must be a positive integer")
        urls = target.get("expected_urls")
        if not isinstance(urls, dict) or not urls:
            problems.append("target.expected_urls must be a non-empty object of "
                            "language -> URL strings")
        else:
            required_langs = _KIND_REQUIRED_URL_LANGS.get(kind or "", frozenset())
            lang_missing = required_langs - urls.keys()
            if lang_missing:
                problems.append(f"target.expected_urls missing required language(s): "
                                f"{', '.join(sorted(lang_missing))}")
            for lang, url in urls.items():
                problems.extend(_validate_url(url, f"target.expected_urls[{lang!r}]"))

    payload = envelope.get("payload")
    if not (isinstance(payload, dict) and payload):
        problems.append("payload must be a non-empty object")
    return problems
