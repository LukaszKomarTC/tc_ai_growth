"""Live-change verification (WP-U4b) — the platform closes the loop the owner used to close.

The owner applies an approved change in WP admin by hand (the remains-manual row of the
eliminated-actions table); the platform then VERIFIES the live pages against the approved
envelope and marks the decision executed. This module implements the spec's §Verification
exactly and fail-closed:

- **Two owner-triggered steps, never one long request.** "Verify live change" performs read #1
  with cache-bypassing headers and records the attempt; a store-backed pending state (derived
  from the attempts table — it survives reloads, sign-outs and restarts) arms "Confirm
  verification" after a minimum interval. The confirm step performs read #2; only two
  consistent full matches mark the decision executed.
- **URL equality is defined, not assumed** (spec r2 pt 4): lowercase scheme/host, strip
  fragment, normalize default ports, canonicalize percent-encoding, the configured
  trailing-slash form required exactly, ANY query = not equal, no broader path normalization.
- **Content comparison**: <title> and meta[name=description] vs the approved payload — Unicode
  NFC, whitespace collapsed, then exact match. Redirects allowed only if the FINAL URL equals
  the expected canonical; the page's <link rel=canonical> must equal it too.
- **Attempts are first-class immutable rows** (store/records.py): per-URL final status,
  redirect chain, fetched title/meta verbatim, body hashes, timestamps, outcome. Success can
  never erase prior failures; `execution_evidence` only POINTS at the terminal attempt.
- **Fail-closed**: ALL languages must match on the SAME read; a missing payload field or an
  unfetchable page is a failure to verify, never a pass.

Only kinds listed in VERIFIABLE_KINDS get an enabled control — a verify path is a registered
capability, not an assumption (spec: no control overstates authority).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html as html_mod
import json
import re
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit

# The kinds this module knows how to verify. The Console enables "Verify live change" ONLY for
# these; adding a kind starts with adding its verification semantics + tests here.
VERIFIABLE_KINDS = frozenset({"seo_meta_update"})

# Spec: the confirm step arms only after a minimum interval — two reads separated in time, so a
# transient (cache flap, mid-edit state) cannot self-confirm. Tests may lower it; production
# never does.
MIN_CONFIRM_INTERVAL_S = 60

_FETCH_TIMEOUT_S = 10
_MAX_BODY_BYTES = 3_000_000

# Sub-delims + colon/at are legal unencoded in paths (RFC 3986); everything else re-encodes.
_PATH_SAFE = "/-._~!$&'()*+,;=:@"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# --- URL equality (pinned rules) -----------------------------------------------------------------


def normalize_url(url: str) -> str | None:
    """The comparison form of a URL under the spec's equality rules. None = not comparable."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        return None
    port = parts.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        host = f"{host}:{port}"
    # Canonical percent-encoding: decode, then re-encode with one fixed safe set — %7E and ~
    # compare equal, while the path TEXT (incl. its trailing-slash form) stays exact.
    path = quote(unquote(parts.path), safe=_PATH_SAFE)
    # Fragment stripped by construction; query participates only as a disqualifier (below).
    return f"{scheme}://{host}{path}"


def urls_equal(a: str, b: str) -> bool:
    """Spec equality: normalized forms equal AND neither carries a query string — a query on
    either side means 'not the approved page', full stop."""
    if urlsplit(a.strip()).query or urlsplit(b.strip()).query:
        return False
    na, nb = normalize_url(a), normalize_url(b)
    return na is not None and na == nb


def normalize_text(s: str) -> str:
    """NFC + whitespace collapse — the ONLY normalization applied before exact match."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()


# --- page signals --------------------------------------------------------------------------------


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(
    r"<meta\s+[^>]*name=[\"']description[\"'][^>]*>", re.IGNORECASE)
_CONTENT_RE = re.compile(r"content=[\"']([^\"']*)[\"']", re.IGNORECASE)
_CANONICAL_RE = re.compile(
    r"<link\s+[^>]*rel=[\"']canonical[\"'][^>]*>", re.IGNORECASE)
_HREF_RE = re.compile(r"href=[\"']([^\"']*)[\"']", re.IGNORECASE)


def extract_page_signals(body: str) -> dict:
    """title / meta description / canonical from an HTML page, HTML-entities decoded, verbatim
    otherwise. Missing pieces come back as None — the comparator treats None as a mismatch."""
    title = None
    m = _TITLE_RE.search(body)
    if m:
        title = html_mod.unescape(m.group(1))
    meta = None
    m = _META_DESC_RE.search(body)
    if m:
        c = _CONTENT_RE.search(m.group(0))
        if c:
            meta = html_mod.unescape(c.group(1))
    canonical = None
    m = _CANONICAL_RE.search(body)
    if m:
        h = _HREF_RE.search(m.group(0))
        if h:
            canonical = h.group(1)
    return {"title": title, "meta_description": meta, "canonical": canonical}


@dataclass
class PageRead:
    """One fetch of one URL — everything the attempt row records about it."""

    requested_url: str
    final_url: str | None = None
    status: int | None = None
    redirect_chain: list[str] = field(default_factory=list)
    body_sha256: str | None = None
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    error: str | None = None


class _ChainRecorder(urllib.request.HTTPRedirectHandler):
    """Records every hop — the spec requires the redirect chain in the evidence row."""

    def __init__(self):
        self.chain: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(url: str, *, timeout_s: float = _FETCH_TIMEOUT_S) -> PageRead:
    """Fetch one page with cache-bypassing headers; never raises — errors are data."""
    read = PageRead(requested_url=url)
    recorder = _ChainRecorder()
    opener = urllib.request.build_opener(recorder)
    req = urllib.request.Request(url, headers={
        "Cache-Control": "no-cache", "Pragma": "no-cache",
        "User-Agent": "tc-growth-verify/1 (+decision verification)"})
    try:
        with opener.open(req, timeout=timeout_s) as resp:
            raw = resp.read(_MAX_BODY_BYTES)
            read.status = resp.status
            read.final_url = resp.geturl()
    except Exception as exc:  # noqa: BLE001 - an unreachable page is evidence, not a crash
        read.error = f"{type(exc).__name__}: {exc}"
        read.redirect_chain = recorder.chain
        return read
    read.redirect_chain = recorder.chain
    read.body_sha256 = hashlib.sha256(raw).hexdigest()
    body = raw.decode("utf-8", errors="replace")
    read.__dict__.update(extract_page_signals(body))
    return read


# --- the per-read verification (pure given a fetcher) --------------------------------------------


def verify_read(envelope: dict, *, fetch=None) -> dict:
    """Fetch EVERY expected URL and compare against the approved payload. Returns
    {"outcome": "match"|"mismatch"|"error", "urls": {lang: {...verbatim evidence + problems}}}.

    Fail-closed: outcome is "match" ONLY if every language fully passes; a fetch error anywhere
    is "error"; anything else wrong anywhere is "mismatch"."""
    fetch = fetch or fetch_page  # resolved at call time so tests can monkeypatch the module attr
    payload = envelope.get("payload") or {}
    expected_urls = (envelope.get("target") or {}).get("expected_urls") or {}
    urls_out: dict = {}
    any_error = False
    all_match = True
    for lang, expected_url in expected_urls.items():
        read = fetch(expected_url)
        problems: list[str] = []
        if read.error:
            problems.append(f"fetch failed: {read.error}")
            any_error = True
        else:
            if read.status != 200:
                problems.append(f"final HTTP status {read.status}, expected 200")
            if not (read.final_url and urls_equal(read.final_url, expected_url)):
                problems.append(f"final URL {read.final_url!r} != expected canonical")
            if not (read.canonical and urls_equal(read.canonical, expected_url)):
                problems.append(f"page canonical {read.canonical!r} != expected URL")
            for kind_label, fetched, payload_key in (
                    ("title", read.title, f"title_{lang}"),
                    ("meta description", read.meta_description, f"meta_{lang}")):
                expected_text = payload.get(payload_key)
                if not isinstance(expected_text, str) or not expected_text.strip():
                    problems.append(f"payload has no {payload_key} to compare — cannot verify")
                elif fetched is None:
                    problems.append(f"page has no {kind_label}")
                elif normalize_text(fetched) != normalize_text(expected_text):
                    problems.append(
                        f"{kind_label} mismatch: fetched {normalize_text(fetched)!r} != "
                        f"approved {normalize_text(expected_text)!r}")
        if problems:
            all_match = False
        urls_out[lang] = {
            "requested_url": read.requested_url, "final_url": read.final_url,
            "status": read.status, "redirect_chain": read.redirect_chain,
            "body_sha256": read.body_sha256, "fetched_title": read.title,
            "fetched_meta_description": read.meta_description,
            "fetched_canonical": read.canonical, "problems": problems,
        }
    outcome = "match" if (all_match and urls_out) else ("error" if any_error else "mismatch")
    if not urls_out:
        outcome = "error"
    return {"outcome": outcome, "urls": urls_out}


# --- the two-step service (store-backed) ---------------------------------------------------------


def confirm_wait_s(pending, *, min_interval_s: int | None = None,
                   now: dt.datetime | None = None) -> int:
    """Seconds until the confirm step arms (0 = armed). The interval is measured from the
    STORED read-#1 finish time, so it survives reloads, sign-outs and service restarts."""
    interval = MIN_CONFIRM_INTERVAL_S if min_interval_s is None else min_interval_s
    now_dt = now or dt.datetime.now(dt.timezone.utc)
    elapsed = (now_dt - dt.datetime.fromisoformat(pending.finished_at)).total_seconds()
    return max(0, int(interval - elapsed))


def verify_step(store, decision, *, step: int, fetch=None,
                min_interval_s: int | None = None, now: dt.datetime | None = None) -> str:
    """Run verification step 1 or 2 for an APPROVED, verifiable decision; returns an outcome
    key the Console maps to a redirect. All policy lives here (unit-testable, no HTTP —
    inject `fetch`); `store` is the backend-neutral Store protocol.

    step 1: read #1 -> attempt row; 'pending' if it fully matched, else its failure outcome.
    step 2: refuse unless an unpaired matching read #1 exists for the CURRENT revision and the
    minimum interval has passed; read #2 -> attempt row; two consistent full matches -> the
    decision becomes EXECUTED (atomic, revision-checked) with the terminal attempt as evidence.
    """
    if decision.status != "approved":
        return "not-approved"
    if not decision.envelope_sha256 or decision.kind not in VERIFIABLE_KINDS:
        return "not-verifiable"
    try:
        envelope = json.loads(decision.envelope or "")
    except (ValueError, TypeError):
        return "not-verifiable"

    if step == 1:
        started = _now_iso()
        result = verify_read(envelope, fetch=fetch)
        store.record_verify_attempt(
            decision_id=decision.id, revision=decision.revision,
            envelope_sha256=decision.envelope_sha256, read_number=1,
            outcome=result["outcome"], detail=json.dumps(result["urls"], ensure_ascii=False),
            started_at=started)
        return "pending" if result["outcome"] == "match" else f"read-{result['outcome']}"

    pending = store.pending_verify_attempt(decision.id, revision=decision.revision)
    if pending is None:
        return "no-pending"
    if confirm_wait_s(pending, min_interval_s=min_interval_s, now=now) > 0:
        return "too-soon"
    started = _now_iso()
    result = verify_read(envelope, fetch=fetch)
    attempt_id = store.record_verify_attempt(
        decision_id=decision.id, revision=decision.revision,
        envelope_sha256=decision.envelope_sha256, read_number=2,
        outcome=result["outcome"], detail=json.dumps(result["urls"], ensure_ascii=False),
        started_at=started, pair_id=pending.id)
    if result["outcome"] != "match":
        return f"read-{result['outcome']}"
    # Two consistent full matches — close the loop. Atomic against the revision the owner saw.
    store.execute_decision(decision.id, expected_revision=decision.revision,
                           evidence_attempt_id=attempt_id, actor="platform")
    return "executed"


# --- U4c: read-only live comparison + adopt-live-content -----------------------------------------


def live_snapshot(envelope: dict, *, fetch=None) -> dict:
    """Read the CURRENT live values for an envelope's target URLs, for display beside the
    proposed ones. Uses the SAME fetch/parse path as verification, so the comparison the owner
    reads can never disagree with the verifier's own judgement.

    Returns `{"fetched_at": iso, "urls": {lang: {"title", "meta_description", "canonical",
    "error"}}}`. A failed read carries `error` and NO values — an unreadable page must look
    unreadable; a previous read is never substituted (review #75: stale cache is never presented
    as current truth)."""
    fetch = fetch or fetch_page
    urls = (envelope.get("target") or {}).get("expected_urls") or {}
    out: dict = {}
    for lang, url in urls.items():
        r = fetch(url)
        out[lang] = {
            "url": url,
            "error": r.error or (None if r.status == 200 else f"HTTP {r.status}"),
            "title": None if r.error else r.title,
            "meta_description": None if r.error else r.meta_description,
            "canonical": None if r.error else r.canonical,
        }
    return {"fetched_at": _now_iso(), "urls": out}


def compare_fields(envelope: dict, snapshot: dict) -> list[dict]:
    """Field-by-field current-vs-proposed rows for the detail page. `same` uses the verifier's
    normalization (NFC + whitespace collapse), so 'differs' here means 'verification would
    fail' — one truth, two surfaces."""
    payload = envelope.get("payload") or {}
    rows: list[dict] = []
    for lang, live in (snapshot.get("urls") or {}).items():
        for label, payload_key, live_key in (("Title", f"title_{lang}", "title"),
                                             ("Meta description", f"meta_{lang}",
                                              "meta_description")):
            proposed = payload.get(payload_key)
            if proposed is None:
                continue
            current = live.get(live_key)
            rows.append({
                "lang": lang, "label": label, "url": live.get("url"),
                "proposed": proposed, "current": current, "error": live.get("error"),
                "same": (current is not None and live.get("error") is None
                         and normalize_text(current) == normalize_text(proposed)),
            })
    return rows


def adopt_live_envelope(envelope: dict, snapshot: dict) -> dict:
    """Compose a NEW envelope whose payload is the live content, keeping target/profile/
    environment/kind unchanged. Raises ValueError when any language could not be read — adopting
    half a page would bind a payload the owner never saw."""
    urls = snapshot.get("urls") or {}
    if not urls:
        raise ValueError("nothing was fetched — cannot adopt live content")
    payload: dict = {}
    for lang, live in urls.items():
        if live.get("error"):
            raise ValueError(f"the {lang} page could not be read ({live['error']}) — "
                             "refusing to adopt a partial snapshot")
        for payload_key, live_key in ((f"title_{lang}", "title"),
                                      (f"meta_{lang}", "meta_description")):
            value = live.get(live_key)
            if value is None:
                raise ValueError(f"the {lang} page has no {live_key} — refusing to adopt")
            payload[payload_key] = value
    new = {k: v for k, v in envelope.items() if k != "payload"}
    new["payload"] = payload
    return new
