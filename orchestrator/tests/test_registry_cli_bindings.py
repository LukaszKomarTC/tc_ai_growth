"""Command-binding invariant (pre-merge review round).

`validate_registry` proves a command-bound operation has a NON-EMPTY command string, but not that
the string resolves to a real CLI entry point — a registry could name `smtp-test` while the CLI
never dispatches it, and nothing would catch the drift until a live run failed. This focused CI
invariant closes that gap: every registry `command` must have a matching dispatch branch in
`cli.py`. No CLI redesign — a test is enough (per review).

This invariant belongs to the Execution-Service layer (it needs both the registry and the CLI
commands present); it is meaningful only once layer 2 is in place.
"""

from __future__ import annotations

import pathlib
import re

from tc_growth.core.actions import OPERATIONS


def _cli_dispatch_commands() -> set[str]:
    """The command literals cli.main() actually dispatches on: `cmd == "x"` and `cmd in (...)`."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "tc_growth" / "cli.py").read_text(encoding="utf-8")
    cmds = set(re.findall(r'cmd == "([\w-]+)"', src))
    for group in re.findall(r'cmd in \(([^)]+)\)', src):
        cmds |= set(re.findall(r'"([\w-]+)"', group))
    return cmds


def test_every_registry_command_has_a_real_cli_entry():
    cli = _cli_dispatch_commands()
    # sanity: the parser found the known accepted-op commands
    assert {"smtp-test", "integrity-scan"} <= cli
    for op in OPERATIONS:
        if op.command is not None:
            assert op.command in cli, (
                f"{op.id}: registry command {op.command!r} has no dispatch branch in cli.py "
                "(the executable registry names a CLI command that does not exist)"
            )
