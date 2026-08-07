"""The only way a U5 collector reaches outside this process.

U5.2 is the first increment whose collectors read real systems, so this is where the "named
read-only collectors, not general shell access" rule of issue #82 §11 becomes code rather than
intent.

The shape of the rule:

* **Fixed argv, never a shell.** `subprocess.run` with a list and no `shell=True`, so there is
  no string for a plugin name or a log line to be interpolated into. A collector names its
  command as a literal tuple in its own module; nothing here builds one from data.
* **Allowlisted programs.** The first element must be one of `_ALLOWED_PROGRAMS`. That is a
  second lock on the same door — a collector cannot invent `rm` even by literal — and it makes
  the complete set of externally-executed programs greppable in one place for review.
* **Bounded time and output.** Every call has a timeout and a byte cap. A command that runs long
  or prints forever yields `unavailable`, not a hung sweep or an unbounded evidence row.
* **Scrubbed environment.** Children inherit a constructed environment, so a collector cannot
  pass anything through it and a subprocess cannot read the Console's secrets.
* **No exceptions escape.** Every failure — missing program, timeout, non-zero exit, decode
  error — becomes a `CommandResult` the collector must inspect. There is deliberately no
  `check=True`: an unreadable source is evidence, and evidence is what this module returns.

Nothing here writes. The allowlist contains no program that can modify state, and the
subcommands each collector passes are read-only by inspection — that is a property of the
call sites, so review them, not just this file.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

#: The complete set of programs U5 collectors may execute. Adding one is a review event.
#: `wp` is the WordPress CLI, already used read-only by the v0 integrity scan under the same
#: service account; the rest are standard read-only system inspection tools.
_ALLOWED_PROGRAMS = frozenset({"wp", "systemctl", "df", "du", "php", "journalctl", "stat"})

#: A collector reads a fact, it does not stream a dataset.
DEFAULT_TIMEOUT_S = 20.0
DEFAULT_OUTPUT_LIMIT = 256 * 1024

#: The constructed environment children get. Deliberately minimal: no TC_* configuration, no
#: credentials, nothing the parent happens to be carrying.
_CHILD_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "HOME": os.environ.get("HOME", "/tmp"),
}


@dataclass(frozen=True)
class CommandResult:
    """What a command did. `ok` means it ran and exited zero — nothing about what it said."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    ok: bool
    unavailable: bool = False
    detail: str = ""

    @property
    def program(self) -> str:
        return self.argv[0] if self.argv else ""


def _unavailable(argv: tuple[str, ...], detail: str) -> CommandResult:
    return CommandResult(argv=argv, returncode=-1, stdout="", stderr="", ok=False,
                         unavailable=True, detail=detail)


def run_command(argv: tuple[str, ...], *, timeout_s: float = DEFAULT_TIMEOUT_S,
                limit: int = DEFAULT_OUTPUT_LIMIT, cwd: str | None = None) -> CommandResult:
    """Run one allowlisted read-only command and return what happened.

    Never raises. A collector's job is to report what it could and could not read, and a
    exception thrown from here would become a bare `unknown` with no dependency named — which is
    exactly the silence issue #82 §14 forbids.
    """
    if not argv:
        return _unavailable((), "no command given")
    program = argv[0]
    if program not in _ALLOWED_PROGRAMS:
        # Not a collector's decision to make. This is unreachable from data — every argv is a
        # literal in a collector module — so reaching it means a code change needs review.
        return _unavailable(tuple(argv), f"{program!r} is not an allowlisted collector program")

    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell, allowlisted program
            list(argv), capture_output=True, timeout=timeout_s, cwd=cwd,
            env=dict(_CHILD_ENV), shell=False, check=False)
    except FileNotFoundError:
        return _unavailable(tuple(argv), f"{program} is not installed on this host")
    except PermissionError as exc:
        return _unavailable(tuple(argv), f"{program} could not be executed: {exc}")
    except subprocess.TimeoutExpired:
        return _unavailable(tuple(argv), f"{program} exceeded {timeout_s:g}s and was stopped")
    except OSError as exc:  # noqa: BLE001 — any OS-level failure is an unreadable source
        return _unavailable(tuple(argv), f"{program} could not be run: {type(exc).__name__}")

    stdout = _decode(proc.stdout, limit)
    stderr = _decode(proc.stderr, 4096)
    return CommandResult(argv=tuple(argv), returncode=proc.returncode, stdout=stdout,
                         stderr=stderr, ok=proc.returncode == 0)


def _decode(raw: bytes, limit: int) -> str:
    """Bound first, then decode. Decoding an unbounded buffer is the hang this cap exists to
    prevent, and `errors="replace"` keeps a binary surprise from raising."""
    if not raw:
        return ""
    return raw[:limit].decode("utf-8", errors="replace")
