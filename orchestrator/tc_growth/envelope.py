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
_TARGET_REQUIRED = frozenset({"object_type", "expected_urls"})


def canonical_json(envelope: dict) -> str:
    """The one canonical text form of an envelope. Every persisted envelope is stored in this
    form, so stored text == hashed text with no re-serialization ambiguity."""
    return json.dumps(envelope, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def envelope_sha256(envelope: dict) -> str:
    return hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()


def validate_envelope(envelope: object) -> list[str]:
    """Structural validation; returns a list of plain-English problems (empty == valid).
    Validates shape and vocabulary only — whether the KIND has an accepted execution path is the
    Action Registry's question, answered at control-render time, not here."""
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
    target = envelope.get("target")
    if not isinstance(target, dict):
        problems.append("target must be an object")
    else:
        t_missing = _TARGET_REQUIRED - target.keys()
        if t_missing:
            problems.append(f"target missing keys: {', '.join(sorted(t_missing))}")
        urls = target.get("expected_urls")
        if not (isinstance(urls, dict) and urls
                and all(isinstance(k, str) and isinstance(v, str) and v.strip()
                        for k, v in urls.items())):
            problems.append("target.expected_urls must be a non-empty object of "
                            "language -> URL strings")
    payload = envelope.get("payload")
    if not (isinstance(payload, dict) and payload):
        problems.append("payload must be a non-empty object")
    return problems
