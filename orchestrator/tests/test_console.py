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


def test_console_phase_defaults_read_only_and_is_overridable(monkeypatch):
    from tc_growth.core.approval import Phase

    monkeypatch.delenv("TC_CONSOLE_PHASE", raising=False)
    assert console._console_phase() is Phase.READ_ONLY
    monkeypatch.setenv("TC_CONSOLE_PHASE", "controlled_execution")
    assert console._console_phase() is Phase.CONTROLLED_EXECUTION
    monkeypatch.setenv("TC_CONSOLE_PHASE", "nonsense")
    assert console._console_phase() is Phase.READ_ONLY
