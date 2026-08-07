"""The only way a U5 collector reaches outside this process.

Issue #82 §11 asks for *named read-only collectors*, not a general command capability. The first
cut of this module allowlisted **program names** and claimed that made it read-only. Review was
right that the claim was false: `php` is a general interpreter and `wp` has write-capable
subcommands, so permitting the executable constrains nothing about the operation. It also
allowlisted `php`, `du`, `df` and `stat`, which no collector used at all — capability granted
against a future that had not been reviewed.

So the boundary is now closed over the exact command **forms** U5.2 needs:

* **Builders, not strings.** A collector calls `wp_plugin_list()`; it never assembles an argv. The
  complete set of commands this platform can run is the list below, readable in one screen.
* **Validated at the door too.** `run_command` matches its argument against the same spec table,
  so even a hand-built argv is refused. `wp plugin install evil` is not a variation on
  `wp plugin list` — it is a different command, and there is no spec for it.
* **One variable slot, tightly typed.** Only the systemd unit varies, and only within a pattern
  that cannot express a flag, a path or a shell metacharacter.
* **Genuinely bounded output.** Output is read incrementally against a byte cap while the child
  runs, and the child is killed when it exceeds it. The previous version used
  `capture_output=True`, which buffers everything the child produces and only *slices* it
  afterwards — that bounds what gets stored, not what gets produced, and the docstring claimed
  otherwise.
* **Bounded time, scrubbed environment, no exception escapes.** A missing program, timeout,
  overflow or decode error becomes a `CommandResult` the collector must inspect. There is no
  `check=True`: an unreadable source is evidence, and evidence is what this module returns.

Every command below is read-only *by form*, which is a property you can check by reading the
table rather than by trusting a comment.
"""

from __future__ import annotations

import os
import re
import selectors
import subprocess
import time
from dataclasses import dataclass

# --- the exact commands this platform may run ---------------------------------------------------

#: systemd fields `platform.services` reads. One fixed string: a caller cannot ask for others.
SYSTEMD_PROPERTIES = ("LoadState,ActiveState,SubState,Result,ExecMainStatus,"
                      "ExecMainExitTimestamp,LastTriggerUSec,NextElapseUSecRealtime")
JOURNAL_WINDOW = "24 hours ago"
JOURNAL_MAX_LINES = "2000"
JOURNAL_PRIORITY = "warning"

#: The only argv element that varies, and it cannot express a flag, a path or a metacharacter.
_UNIT_RE = re.compile(r"^[A-Za-z0-9@:._-]{1,64}\.(service|timer)$")


class _UnitSlot:
    """Marks the one position in a spec where a caller-supplied value is permitted."""

    def matches(self, value: str) -> bool:
        return bool(_UNIT_RE.match(value))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unit>"


_UNIT = _UnitSlot()

#: The complete set of externally-executed commands. Adding an entry is a review event; adding a
#: *program* is a bigger one. Every form here is read-only — `list`, `show`, `version`, a journal
#: read — and none can be turned into a write by changing an argument, because no argument varies
#: except the unit name.
_ALLOWED_COMMANDS: tuple[tuple, ...] = (
    ("wp", "core", "version"),
    ("wp", "plugin", "list", "--format=json", "--fields=name,status,version,update"),
    ("wp", "theme", "list", "--format=json", "--fields=name,status,version"),
    ("systemctl", "show", _UNIT, f"--property={SYSTEMD_PROPERTIES}"),
    ("journalctl", "-u", _UNIT, "--since", JOURNAL_WINDOW, "--no-pager", "-o", "cat",
     "-n", JOURNAL_MAX_LINES, "-p", JOURNAL_PRIORITY),
    ("journalctl", "-u", _UNIT, "--no-pager", "-o", "cat", "-n", "1"),
)


# --- builders: the only supported way to produce an argv -----------------------------------------

def wp_core_version() -> tuple[str, ...]:
    return _ALLOWED_COMMANDS[0]


def wp_plugin_list() -> tuple[str, ...]:
    return _ALLOWED_COMMANDS[1]


def wp_theme_list() -> tuple[str, ...]:
    return _ALLOWED_COMMANDS[2]


def systemctl_show(unit: str) -> tuple[str, ...]:
    return ("systemctl", "show", unit, f"--property={SYSTEMD_PROPERTIES}")


def journalctl_window(unit: str) -> tuple[str, ...]:
    return ("journalctl", "-u", unit, "--since", JOURNAL_WINDOW, "--no-pager", "-o", "cat",
            "-n", JOURNAL_MAX_LINES, "-p", JOURNAL_PRIORITY)


def journalctl_probe(unit: str) -> tuple[str, ...]:
    """One line, unfiltered — evidence that a unit logs here at all."""
    return ("journalctl", "-u", unit, "--no-pager", "-o", "cat", "-n", "1")


def is_allowed(argv: tuple[str, ...]) -> bool:
    """Does this argv match one of the permitted forms, element for element?"""
    for spec in _ALLOWED_COMMANDS:
        if len(spec) != len(argv):
            continue
        if all(slot.matches(value) if isinstance(slot, _UnitSlot) else slot == value
               for slot, value in zip(spec, argv)):
            return True
    return False


# --- execution ----------------------------------------------------------------------------------

DEFAULT_TIMEOUT_S = 20.0
DEFAULT_OUTPUT_LIMIT = 256 * 1024
STDERR_LIMIT = 4096

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
    """Run one permitted read-only command and return what happened. Never raises."""
    argv = tuple(argv)
    if not argv:
        return _unavailable((), "no command given")
    if not is_allowed(argv):
        # Unreachable from data — collectors use the builders — so reaching it means a code
        # change that needs review, or an argv that is simply not one of the permitted forms.
        return _unavailable(argv, f"{argv[0]!r} was not called in a permitted read-only form")

    try:
        proc = subprocess.Popen(  # noqa: S603 — spec-validated argv, no shell
            list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
            env=dict(_CHILD_ENV), shell=False)
    except FileNotFoundError:
        return _unavailable(argv, f"{argv[0]} is not installed on this host")
    except PermissionError as exc:
        return _unavailable(argv, f"{argv[0]} could not be executed: {exc}")
    except OSError as exc:  # noqa: BLE001 — any OS-level failure is an unreadable source
        return _unavailable(argv, f"{argv[0]} could not be run: {type(exc).__name__}")

    return _drain(proc, argv, timeout_s=timeout_s, limit=limit)


def _drain(proc: subprocess.Popen, argv: tuple[str, ...], *, timeout_s: float,
           limit: int) -> CommandResult:
    """Read the child's output incrementally, enforcing the byte cap WHILE it runs.

    A child that keeps producing past the cap is killed rather than buffered: the cap is meant
    to bound what this process handles, not merely what it keeps.
    """
    out, err = bytearray(), bytearray()
    deadline = time.monotonic() + timeout_s
    overflow = False

    sel = selectors.DefaultSelector()
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            sel.register(stream, selectors.EVENT_READ)
    try:
        while sel.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate(proc)
                return _unavailable(argv, f"{argv[0]} exceeded {timeout_s:g}s and was stopped")
            for key, _ in sel.select(timeout=min(0.2, remaining)):
                chunk = key.fileobj.read1(65536)  # type: ignore[union-attr]
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                buffer = out if key.fileobj is proc.stdout else err
                cap = limit if buffer is out else STDERR_LIMIT
                room = cap - len(buffer)
                if room > 0:
                    buffer.extend(chunk[:room])
                if len(chunk) > room:
                    overflow = overflow or buffer is out
    except OSError as exc:  # noqa: BLE001 — a broken pipe mid-read is an unreadable source
        _terminate(proc)
        return _unavailable(argv, f"{argv[0]} output could not be read: {type(exc).__name__}")
    finally:
        sel.close()
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()

    if overflow:
        _terminate(proc)
        return _unavailable(argv, f"{argv[0]} produced more than {limit} bytes and was stopped")

    try:
        returncode = proc.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        _terminate(proc)
        return _unavailable(argv, f"{argv[0]} exceeded {timeout_s:g}s and was stopped")

    return CommandResult(argv=argv, returncode=returncode,
                         stdout=out.decode("utf-8", errors="replace"),
                         stderr=err.decode("utf-8", errors="replace"),
                         ok=returncode == 0)


def _terminate(proc: subprocess.Popen) -> None:
    """Stop a child that ran too long or said too much, and do not wait forever for it to go."""
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001 — the process is already gone, or beyond our reach
        pass
