"""WP-U4d.2 — the dedicated deploy venv shape (regression for the on-host A2 finding).

On-host preparation (runbook step A2) surfaced a real production discovery: the Console runs from
a service-user-owned, **editable** virtualenv (`pip install -e`), and the installer correctly
**refused** to bless it as the privileged deploy interpreter. Refusal is the boundary working, not
a bug — a root-owned interpreter that imports `tc_growth` back out of a service-user-writable tree
would satisfy every ownership check and still leave the running application mutable. The fix is a
**dedicated, root-owned, non-editable deploy venv**, separate from the long-running Console venv,
which stays untouched.

This test pins the two install shapes so the gap cannot silently reappear, and it runs
**unprivileged** — so CI actually exercises it rather than skipping it as it does the root-only
boundary suite:

- a **non-editable** install (`pip install .`, the dedicated deploy venv) lands `tc_growth` inside
  the venv's own site-packages and writes **no** `.pth`/`__editable__*` finder that redirects
  imports into the source checkout — the exact shape `assert_no_import_path_into_mutable_trees`
  in `tc-deploy-privileged.sh` accepts;
- an **editable** install (`pip install -e .`, the Console venv) writes an `__editable__*` finder
  whose target is the service-user-writable source tree, and `tc_growth` resolves from there — the
  exact shape the guard refuses.

The predicate here mirrors the privileged program's guard verbatim: a `.pth`/`__editable__*` file
under a site-packages directory whose content names the mutable source tree.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# The real package source: <repo>/orchestrator (this file is <repo>/orchestrator/tests/…).
ORCHESTRATOR = Path(__file__).resolve().parents[1]


def _run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=None if cwd is None else str(cwd),
                          capture_output=True, text=True, timeout=600)


def _make_venv(where: Path) -> Path:
    """A plain virtualenv with the interpreter's bundled pip/setuptools.

    The install below uses --no-build-isolation so nothing is fetched from the network: the build
    backend (setuptools) must already live in the venv. Python 3.11 — CI's pinned version — ships
    it via ensurepip; if a future interpreter drops it, the test skips rather than failing on an
    environment gap it is not testing.
    """
    proc = _run(sys.executable, "-m", "venv", str(where))
    assert proc.returncode == 0, proc.stderr
    py = where / "bin" / "python"
    if _run(str(py), "-c", "import setuptools").returncode != 0:
        pytest.skip("this interpreter's venv has no bundled setuptools; "
                    "offline --no-build-isolation install is not available here")
    return py


def _pip_install(py: Path, *extra: str) -> subprocess.CompletedProcess:
    # --no-deps: the third-party runtime deps are irrelevant to the import-origin shape and would
    #   otherwise require the network. --no-build-isolation: build with the venv's own setuptools,
    #   so the wheel is produced offline.
    return _run(str(py), "-m", "pip", "install", "--no-deps", "--no-build-isolation",
                "--disable-pip-version-check", "-q", *extra, str(ORCHESTRATOR))


def _site_dirs(py: Path) -> list[Path]:
    out = _run(str(py), "-c",
               "import site,sys,json;"
               "p=set(sys.path);"
               "p.update(getattr(site,'getsitepackages',lambda:[])());"
               "p.add(site.getusersitepackages());"
               "print(json.dumps([x for x in p if x]))").stdout
    return [Path(p) for p in json.loads(out) if Path(p).is_dir()]


def _import_origin(py: Path) -> str:
    # From a neutral cwd (the repo root would put the source tree's own `tc_growth` on sys.path via
    # '' and mask what the install actually resolves).
    out = _run(str(py), "-c", "import tc_growth;print(tc_growth.__file__)", cwd=Path("/"))
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def _redirects_into_mutable_tree(py: Path, mutable: Path) -> Path | None:
    """The privileged program's exact predicate: a `.pth`/`__editable__*` file under any
    site-packages directory whose content names the service-user-writable source tree."""
    needle = str(mutable)
    for site in _site_dirs(py):
        for finder in list(site.glob("*.pth")) + list(site.glob("__editable__*")):
            try:
                if needle in finder.read_text(errors="ignore"):
                    return finder
            except OSError:
                continue
    return None


def test_non_editable_deploy_venv_imports_from_its_own_site_packages(tmp_path):
    """The dedicated deploy venv: `pip install .` — `tc_growth` lives inside the venv, and nothing
    redirects imports back into the source checkout. This is what the privileged boundary accepts.
    """
    py = _make_venv(tmp_path / "deploy")
    installed = _pip_install(py)
    assert installed.returncode == 0, installed.stderr

    origin = Path(_import_origin(py))
    assert str(origin).startswith(str(tmp_path / "deploy")), \
        f"tc_growth resolved from {origin}, not the deploy venv's own site-packages"
    assert not str(origin).startswith(str(ORCHESTRATOR)), \
        f"tc_growth resolved out of the mutable source tree {ORCHESTRATOR}"

    offender = _redirects_into_mutable_tree(py, ORCHESTRATOR)
    assert offender is None, f"a non-editable install left an import-redirecting finder: {offender}"


def test_editable_console_venv_redirects_into_the_mutable_source_tree(tmp_path):
    """The Console venv shape: `pip install -e .` — an `__editable__*` finder points `tc_growth`
    back at the service-user-writable source tree. This is exactly what the privileged boundary
    refuses, and why the Console venv cannot double as the deploy interpreter.
    """
    py = _make_venv(tmp_path / "console")
    installed = _pip_install(py, "-e")
    assert installed.returncode == 0, installed.stderr

    origin = Path(_import_origin(py))
    assert str(origin).startswith(str(ORCHESTRATOR)), \
        f"an editable install should resolve tc_growth from the source tree; got {origin}"

    offender = _redirects_into_mutable_tree(py, ORCHESTRATOR)
    assert offender is not None, \
        "an editable install must leave a .pth/__editable__ finder into the source tree"


def test_the_two_shapes_differ_exactly_at_the_boundary_the_guard_checks(tmp_path):
    """Side by side, one assertion: the dedicated (non-editable) deploy venv is clean and the
    Console (editable) venv is not — the precise, single distinction the on-host A2 finding turned
    on. If a future change made `pip install .` emit a redirecting finder, or the guard stopped
    keying on it, this fails.
    """
    deploy_py = _make_venv(tmp_path / "deploy")
    assert _pip_install(deploy_py).returncode == 0

    console_py = _make_venv(tmp_path / "console")
    assert _pip_install(console_py, "-e").returncode == 0

    assert _redirects_into_mutable_tree(deploy_py, ORCHESTRATOR) is None
    assert _redirects_into_mutable_tree(console_py, ORCHESTRATOR) is not None
