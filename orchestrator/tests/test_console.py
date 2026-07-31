"""Operations Console auth + guard tests (WP-CONSOLE-MVP slice 1, UI half).

The Console is a privileged execution surface, so its access control is the thing under test:
the shared-token session must be unforgeable and expiring, the CSRF token must be bound to the
session, and the server must fail closed when no token is configured. The execution itself is
covered by test_executor.py — here we test the door, not the room.
"""

from __future__ import annotations

from tc_growth import console

SECRET = b"correct-horse-battery-staple"


# -- session signing -----------------------------------------------------------


def test_issued_session_validates_and_is_unforgeable():
    now = 1_000_000
    tok = console.issue_session(SECRET, now=now)
    assert console.valid_session(tok, SECRET, now=now)
    # A different secret cannot validate the same token.
    assert not console.valid_session(tok, b"attacker-guess", now=now)


def test_tampered_session_is_rejected():
    tok = console.issue_session(SECRET, now=1_000_000)
    ts, sig = tok.split(".", 1)
    # Flip the timestamp but keep the signature — must fail (sig no longer matches).
    forged = f"{int(ts) + 1}.{sig}"
    assert not console.valid_session(forged, SECRET, now=1_000_000)
    # Garbage shapes never validate.
    for bad in (None, "", "no-dot", "abc.def", ".", "123."):
        assert not console.valid_session(bad, SECRET, now=1_000_000)


def test_session_expires():
    tok = console.issue_session(SECRET, now=1_000_000)
    assert console.valid_session(tok, SECRET, now=1_000_000 + console._SESSION_MAX_AGE)
    assert not console.valid_session(tok, SECRET, now=1_000_000 + console._SESSION_MAX_AGE + 1)
    # A session stamped in the future (clock skew / forgery) is not accepted either.
    assert not console.valid_session(tok, SECRET, now=999_999)


# -- CSRF binding --------------------------------------------------------------


def test_csrf_is_bound_to_the_session_and_secret():
    session = console.issue_session(SECRET, now=1_000_000)
    token = console.csrf_for(session, SECRET)
    assert console.valid_csrf(token, session, SECRET)
    # Wrong session, wrong secret, or missing token all fail.
    other = console.issue_session(SECRET, now=1_000_001)
    assert not console.valid_csrf(token, other, SECRET)
    assert not console.valid_csrf(token, session, b"attacker-guess")
    assert not console.valid_csrf(None, session, SECRET)
    assert not console.valid_csrf("", session, SECRET)


# -- fail-closed ---------------------------------------------------------------


def test_serve_refuses_without_a_token(monkeypatch, capsys):
    monkeypatch.delenv(console._TOKEN_ENV, raising=False)
    rc = console.serve()
    assert rc == 1
    assert "REFUSING TO START" in capsys.readouterr().out


def test_secret_reads_the_env(monkeypatch):
    monkeypatch.setenv(console._TOKEN_ENV, "  spaced-token  ")
    assert console._secret() == b"spaced-token"
    monkeypatch.setenv(console._TOKEN_ENV, "")
    assert console._secret() is None


# -- phase selection -----------------------------------------------------------


def test_redeploy_invalidates_existing_sessions(monkeypatch):
    """A new deploy (new TC_BUILD_COMMIT) must invalidate sessions minted by the old build — a
    code change on a privileged execution surface is a natural point to force re-auth."""
    monkeypatch.setenv("TC_BUILD_COMMIT", "build-1")
    tok = console.issue_session(SECRET, now=1_000_000)
    assert console.valid_session(tok, SECRET, now=1_000_000)
    csrf = console.csrf_for(tok, SECRET)
    # redeploy: the epoch changes
    monkeypatch.setenv("TC_BUILD_COMMIT", "build-2")
    assert not console.valid_session(tok, SECRET, now=1_000_000)   # old session rejected
    assert not console.valid_csrf(csrf, tok, SECRET)               # old CSRF rejected too


def test_environment_badge_is_unmissable():
    """F2: PRODUCTION renders as a distinct filled badge; staging gets its own class — the
    environment must be impossible to misread on an execution surface."""
    prod = console._shell("t", "operations", "x", site_name="Tossa Cycling", env_kind="production")
    assert "envbadge prod" in prod and ">PRODUCTION<" in prod
    stag = console._shell("t", "operations", "x", site_name="Tossa Cycling", env_kind="staging")
    assert "envbadge stag" in stag and ">STAGING<" in stag
    # unset/blank env falls back to staging, never silently blank
    dflt = console._shell("t", "operations", "x", site_name="TC", env_kind="")
    assert ">STAGING<" in dflt


def test_redact_reduces_docroot_header_but_keeps_wp_relative_findings():
    """F3: the scanner's header names the absolute docroot — the stream must reduce it, while
    WP-relative finding paths keep their diagnostic meaning."""
    header = console._redact(
        "Technical Inspector — integrity anomalies on /var/www/vhosts/tossacycling.com/httpdocs at ...")
    assert "/var/www/" not in header and "httpdocs" in header
    finding = console._redact("wp-content/uploads/tc-acceptance-fixture.php")
    assert finding == "wp-content/uploads/tc-acceptance-fixture.php"  # relative path untouched


def test_ui_redacts_server_prefix_but_keeps_meaningful_path():
    """Redaction strips the server-mount prefix but must NOT destroy diagnostic meaning — the
    operator still needs uploads vs mu-plugins, scanner vs WordPress root."""
    # bare tool path with no WP marker -> basename (server layout gone)
    red = console._redact("scanner: /usr/local/bin/wp-integrity-scan.sh sha256=abc")
    assert "/usr/local/bin/" not in red and "wp-integrity-scan.sh" in red
    # WordPress finding paths -> mount prefix stripped, meaningful tail preserved AND distinct
    up = console._redact("/var/www/vhosts/tossacycling.com/httpdocs/wp-content/uploads/evil.php")
    mu = console._redact("/var/www/vhosts/tossacycling.com/httpdocs/wp-content/mu-plugins/x.php")
    assert "/var/www/" not in up and "/var/www/" not in mu
    assert up.endswith("wp-content/uploads/evil.php")
    assert mu.endswith("wp-content/mu-plugins/x.php")
    assert up != mu  # the two targets remain distinguishable — evidence is not flattened


def test_logs_label_findings_as_completed_and_escape_scanner_output(monkeypatch):
    """Two guarantees in one: a findings run must read as 'completed', never 'failed'; and any
    scanner output rendered into the logs page must be HTML-escaped (no stored XSS from a
    filename or a log line the attacker controls)."""
    import json
    import types

    run = types.SimpleNamespace(
        kind="op:run_integrity_scan", status="completed", started_at="2026-07-28T06:20:00Z",
        summary="<script>alert(1)</script> ADMIN set changed",
        detail=json.dumps({"outcome": "findings", "severity": "attention"}),
    )
    fake_store = types.SimpleNamespace(list_runs=lambda: [run])
    monkeypatch.setattr("tc_growth.store.open_store", lambda: fake_store)

    html_out = console._logs_body()
    assert "completed · findings" in html_out          # not "failed"
    assert "<script>alert(1)</script>" not in html_out  # escaped, not live
    assert "&lt;script&gt;" in html_out


def test_stream_client_escapes_output_via_textcontent():
    """The live step stream renders attacker-influenced output client-side; it must go through the
    textContent-based escaper, never innerHTML directly. Guard against that helper being dropped."""
    # The operations page carries the client script.
    assert "textContent" in console._SCRIPT
    assert "h(ev.detail)" in console._SCRIPT and "h(ev.step)" in console._SCRIPT


def test_console_phase_defaults_read_only_and_is_overridable(monkeypatch):
    from tc_growth.core.approval import Phase

    monkeypatch.delenv("TC_CONSOLE_PHASE", raising=False)
    assert console._console_phase() is Phase.READ_ONLY
    monkeypatch.setenv("TC_CONSOLE_PHASE", "controlled_execution")
    assert console._console_phase() is Phase.CONTROLLED_EXECUTION
    monkeypatch.setenv("TC_CONSOLE_PHASE", "nonsense")
    assert console._console_phase() is Phase.READ_ONLY
