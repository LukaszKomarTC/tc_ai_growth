"""`wp.inventory` — what WordPress is actually running.

Read-only: `core version`, `plugin list`, `theme list`. No `update`, no `install`, no `activate`.
wp-cli runs with `cwd` set to the docroot rather than a `--path` argument, so every argv element
stays a literal in this module and nothing built from configuration reaches the command line.

**This is monitoring, not an update nagscreen** (issue #82 §6.1). The collector records whether
an update is *available* as a plain fact alongside the installed version, and never lets it
influence status. Four different things get four different answers:

* *observed version drift* — this inventory differs from the last one. Interesting, informational.
* *update availability* — a newer version exists upstream. Not a problem; recorded, never a warning.
* *malfunction* — an active plugin has vanished, or WordPress cannot be read at all.
* *unknown* — wp-cli is missing, the docroot is unset, or the output did not parse.

Conflating the first two is how monitoring becomes noise, and noise is how a real finding gets
missed.
"""

from __future__ import annotations

import json
import os
from typing import Callable

from ..inspection import STATUS_ACTION, STATUS_OK, STATUS_UNKNOWN, CollectionContext, CollectorResult
#: Part of the deployed service's GOVERNED configuration since U5.2b: `deploy-console.sh` writes
#: it into the unit, so the owner never pastes it before a run and the Console can say on its own
#: page whether it is set. There is deliberately no default — guessing a docroot would mean
#: inspecting whichever site happens to live at a familiar path and filing the result under this
#: profile's name, the cross-identity failure U5 exists to prevent. One owner for the contract:
#: the collector that READS it must not be a second place that NAMES it.
from ..runtime_identity import (DOCROOT_ENV, DOCROOT_INACCESSIBLE, DOCROOT_MISSING,
                                DOCROOT_READABLE, DOCROOT_UNSET, DOCROOT_UNVERIFIED,
                                probe_docroot)
from ._exec import CommandResult, run_command, wp_core_version, wp_plugin_list, wp_theme_list

# The argv comes from `_exec`'s builders: a collector names the command it wants and cannot
# assemble one, so `wp plugin install` is not a variation this module could express.
_CORE = wp_core_version()
_PLUGINS = wp_plugin_list()
_THEMES = wp_theme_list()

Runner = Callable[..., CommandResult]


class WpInventoryCollector:
    id = "wp.inventory"
    version = "1"
    scope = "wp.inventory"

    def __init__(self, *, runner: Runner | None = None, docroot: str | None = None):
        self._run = runner or run_command
        self._docroot = docroot

    #: One sentence per docroot state, because four different problems have four different
    #: fixes. The old wording — "not set to a readable directory" — was said about a docroot that
    #: WAS set, whose real problem was that the service account could not traverse to it, and it
    #: pointed the reader at the configuration instead of the permission (issue #82, U5.2d).
    _DOCROOT_REASON = {
        DOCROOT_UNSET: (
            f"{DOCROOT_ENV} is not set in this service's environment, so WordPress was not "
            f"inspected"),
        DOCROOT_MISSING: (
            f"{DOCROOT_ENV} is set, but there is no directory at that path, so WordPress was "
            f"not inspected"),
        DOCROOT_INACCESSIBLE: (
            f"{DOCROOT_ENV} points at a directory this service cannot open — it is there, but "
            f"the account this platform runs as cannot traverse or list it, which is what "
            f"wp-cli needs"),
        DOCROOT_UNVERIFIED: (
            f"{DOCROOT_ENV} could not be examined at all — the filesystem returned an error "
            f"establishing neither absence nor refusal, so its state is genuinely unknown"),
    }

    def _resolve_docroot(self) -> tuple[str, str]:
        """The configured docroot and what was ESTABLISHED about it.

        Uses the canonical `probe_docroot` rather than making a second `os.path.isdir()` decision
        — one truth about the governed docroot, in one place. `isdir()` cannot tell absence from
        an unreachable parent, which is how this collector came to report a set docroot as unset.
        """
        root = self._docroot if self._docroot is not None else os.environ.get(DOCROOT_ENV, "")
        root = (root or "").strip()
        return root, probe_docroot(root)

    def collect(self, ctx: CollectionContext) -> CollectorResult:
        docroot, state = self._resolve_docroot()
        if state != DOCROOT_READABLE:
            return self._unknown(self._DOCROOT_REASON[state],
                                 f"{DOCROOT_ENV}={docroot or '(unset)'} — {state}")

        core = self._run(_CORE, cwd=docroot)
        if core.unavailable:
            return self._unknown("wp-cli could not be run, so WordPress state is unknown",
                                 core.detail)
        if not core.ok:
            return self._unknown("wp-cli could not read this WordPress installation",
                                 core.stderr.strip()[:300])

        plugins, p_err = self._json_list(_PLUGINS, docroot)
        themes, t_err = self._json_list(_THEMES, docroot)
        if plugins is None or themes is None:
            return self._unknown(
                "WordPress answered, but its inventory did not parse — treating the reading as "
                "unusable rather than reporting a partial one",
                "; ".join(e for e in (p_err, t_err) if e))

        active = [p for p in plugins if p.get("status") == "active"]
        must_use = [p for p in plugins if p.get("status") == "must-use"]
        # Recorded, never escalated. See the module docstring.
        updatable = [p["name"] for p in plugins if p.get("update") == "available"]

        value = {
            "core": {"version": core.stdout.strip()},
            "plugins": sorted(
                ({"name": p.get("name", ""), "status": p.get("status", ""),
                  "version": p.get("version", "")} for p in plugins),
                key=lambda p: p["name"]),
            "themes": sorted(
                ({"name": t.get("name", ""), "status": t.get("status", ""),
                  "version": t.get("version", "")} for t in themes),
                key=lambda t: t["name"]),
            "counts": {"plugins": len(plugins), "active": len(active),
                       "must_use": len(must_use), "themes": len(themes)},
            "updates_available": sorted(updatable),
        }

        # What is INSTALLED here, minus what is available elsewhere. `updates_available` is a
        # fact about upstream release schedules, not about this host: WordPress publishing 6.9
        # would otherwise make this scope report that the site changed, on a site nobody
        # touched. The module docstring already says update availability must never influence
        # status — until now that was true of the collector and false of the digest taken over
        # its output.
        material = {k: value[k] for k in ("core", "plugins", "themes", "counts")}

        # The one condition this collector treats as a malfunction on a single reading: a
        # WordPress with no active plugins is not a tidy site, it is a broken one.
        if not active:
            return CollectorResult(
                scope=self.scope, status=STATUS_ACTION, value=value, source="wp-cli",
                evidence=f"docroot {docroot}",
                reason="WordPress reports no active plugins at all, which a working site does not",
                confidence="high", material=material, comparable=True)

        note = (f"{len(updatable)} update(s) available — recorded, not a fault"
                if updatable else "no updates pending")
        return CollectorResult(
            scope=self.scope, status=STATUS_OK, value=value, source="wp-cli",
            evidence=f"docroot {docroot}; core {core.stdout.strip()}",
            reason=f"WordPress {core.stdout.strip()} with {len(active)} active plugin(s); {note}",
            confidence="high", material=material, comparable=True)

    def _json_list(self, argv: tuple[str, ...], docroot: str) -> tuple[list[dict] | None, str]:
        result = self._run(argv, cwd=docroot)
        if result.unavailable or not result.ok:
            return None, (result.detail or result.stderr.strip())[:200]
        try:
            parsed = json.loads(result.stdout or "[]")
        except ValueError as exc:
            return None, f"{argv[1]} list did not parse: {exc}"
        if not isinstance(parsed, list):
            return None, f"{argv[1]} list was not a list"
        return [p for p in parsed if isinstance(p, dict)], ""

    def _unknown(self, reason: str, evidence: str) -> CollectorResult:
        """No inventory was read, so no material state was established — `comparable=False`.
        Comparing one "wordpress inventory unavailable" against the next would turn a changing
        error message into drift (issue #82, U5.2d)."""
        return CollectorResult(scope=self.scope, status=STATUS_UNKNOWN,
                               value={"error": "wordpress inventory unavailable"},
                               source="wp-cli", evidence=evidence, reason=reason,
                               confidence="none", comparable=False)
