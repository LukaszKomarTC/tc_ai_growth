"""WP-U4d.1 — the deployment target seam is reachable from the command line and nowhere else.

The seam exists so a disposable target can be driven for real. That is worth having only if the
seam cannot be reached from a request, and PR #79's lesson is that "no handler passes one" is an
argument about source, not a property.

So the central test here starts a **real Console in its own process**, drives real HTTP requests at
it, and then asks that process whether it can select a deployment target. It cannot — and the same
test first proves the process COULD before it served anything, so the refusal is the request
boundary doing work rather than the check being vacuous.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import re
import select
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from tc_growth import console, deploy, deploy_target
from tc_growth.store.sqlite import SqliteStore

SHA = "684681cb72a1e6790c13718eeb786ded2b16c8aa"
PKG_PARENT = os.path.dirname(os.path.dirname(deploy.__file__))


@pytest.fixture(autouse=True)
def _clean_gate():
    """The gate flags are process-global by design. Reset around every test so one test's state
    cannot silently satisfy another's assertion — the real proof runs in its own process anyway."""
    deploy_target._reset_for_tests()
    yield
    deploy_target._reset_for_tests()


def _disposable_fields(tmp_path, **overrides) -> dict:
    fields = {
        "name": "probe",
        "app_dir": str(tmp_path / "app"),
        "releases_dir": str(tmp_path / "releases"),
        "backup_dir": str(tmp_path / "backups"),
        "db_path": str(tmp_path / "state" / "store.db"),
        "venv": str(tmp_path / "venv"),
        "service": "tc-console-probe",
        "unit_prefix": "tc-deploy-probe",
        "evidence_namespace": "disposable/probe",
        "port": "8999",
    }
    fields.update(overrides)
    return fields


# --- only the command line may select a target ------------------------------------------------

def test_no_target_can_be_constructed_while_the_gate_is_closed(tmp_path):
    with pytest.raises(deploy.DeployRefused) as exc:
        deploy_target.Target(**_disposable_fields(tmp_path), disposable=True)
    assert "command-line gate" in str(exc.value)
    with pytest.raises(deploy.DeployRefused):
        deploy_target.make_disposable_target(**_disposable_fields(tmp_path))


def test_the_gate_lets_the_command_line_build_a_disposable_target(tmp_path):
    """The control for the test above: with the gate open the same call succeeds, so the refusal
    is the gate and not a malformed argument."""
    deploy_target.open_cli_target_gate()
    target = deploy_target.make_disposable_target(**_disposable_fields(tmp_path))
    assert target.disposable is True
    assert target.name == "probe"
    assert target.unit_name(SHA) == "tc-deploy-probe-684681cb72a1"


def test_production_is_a_singleton_and_is_never_rebuilt_from_arguments(tmp_path):
    """Even with the gate open, the one thing that may not be constructed is another production:
    a second 'production' target is how a disposable run would quietly become a real one."""
    deploy_target.open_cli_target_gate()
    with pytest.raises(deploy.DeployRefused) as exc:
        deploy_target.Target(**_disposable_fields(tmp_path, name="production"), disposable=False)
    assert "singleton" in str(exc.value)


@pytest.mark.parametrize("bad", [
    {"app_dir": "relative/path"},
    {"app_dir": "/opt/../etc"},
    {"releases_dir": ""},
    {"service": "tc console"},
    {"service": "../../etc/systemd/system/anything"},
    {"unit_prefix": "tc-deploy;reboot"},
    {"name": "Production"},
    {"name": "../escape"},
    {"port": "eight-thousand"},
])
def test_a_malformed_target_is_refused_even_from_the_command_line(tmp_path, bad):
    """The gate says WHO may build a target; these say WHAT a target may be. Both are needed —
    a CLI-only seam that accepts `/etc` is still a way to write to `/etc`."""
    deploy_target.open_cli_target_gate()
    with pytest.raises(deploy.DeployRefused):
        deploy_target.make_disposable_target(**_disposable_fields(tmp_path, **bad))


def test_the_default_target_is_production_and_a_name_is_not_a_target():
    """There is no name-to-target table to index into. A string where a Target belongs is refused
    rather than resolved, because a lookup table is the shape an injection wants."""
    assert deploy.target_of(None) is deploy_target.PRODUCTION
    assert deploy.target_of({}) is deploy_target.PRODUCTION
    assert deploy.target_of({"target": None}) is deploy_target.PRODUCTION
    for name in ("production", "disposable", "../../etc"):
        with pytest.raises(deploy.DeployRefused):
            deploy.target_of({"target": name})


# --- the Console cannot select a target, proven against a real Console process ------------------

_DRIVER = textwrap.dedent("""
    import json, sys, threading
    from http.server import ThreadingHTTPServer

    sys.path.insert(0, {pkg_parent!r})
    from tc_growth import console, deploy, deploy_target

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), console._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("PORT %d" % httpd.server_address[1], flush=True)

    def probe():
        # Can this process select a deployment target right now?
        try:
            deploy_target.open_cli_target_gate()
            gate = "open"
        except deploy.DeployRefused as exc:
            gate = "refused: %s" % exc
        try:
            deploy_target.make_disposable_target(
                name="injected", app_dir="/tmp/injected/app",
                releases_dir="/tmp/injected/releases", backup_dir="/tmp/injected/backups",
                db_path="/tmp/injected/store.db", venv="/tmp/injected/venv",
                service="tc-console-injected", unit_prefix="tc-deploy-injected",
                evidence_namespace="disposable/injected", port="9999")
            built = "built"
        except deploy.DeployRefused as exc:
            built = "refused: %s" % exc
        return {{"gate": gate, "built": built,
                 "resolved": deploy.target_of({{}}).name,
                 "resolved_app_dir": deploy.target_of({{}}).app_dir,
                 "latched": deploy_target.http_boundary_latched()}}

    for line in sys.stdin:
        if line.strip() == "probe":
            print("PROBE " + json.dumps(probe()), flush=True)
        elif line.strip() == "quit":
            break
""")

#: Every field name a request could plausibly use to name a target, aimed at every deploy route.
_INJECTIONS = {
    "target": "injected", "target_name": "injected", "app_dir": "/tmp/injected/app",
    "releases_dir": "/tmp/injected/releases", "backup_dir": "/tmp/injected/backups",
    "db_path": "/tmp/injected/store.db", "service": "tc-console-injected",
    "unit": "tc-deploy-injected", "unit_prefix": "tc-deploy-injected", "venv": "/tmp/injected/venv",
    "evidence_namespace": "disposable/injected", "disposable": "true",
}


def _readline(proc, *, timeout: float, what: str) -> str:
    """A readline that CANNOT hang the suite.

    `proc.stdout.readline()` blocks forever if the child is alive but wedged, which would turn a
    failing test into a stuck CI job — and a job that hangs tells you nothing about which
    assertion broke. `select` bounds the wait; running out of time is a test failure with a name.
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"timed out after {timeout:g}s waiting for {what}")
        if not select.select([proc.stdout], [], [], min(remaining, 0.5))[0]:
            if proc.poll() is not None:
                raise AssertionError(f"the Console driver exited ({proc.returncode}) "
                                     f"while waiting for {what}")
            continue
        line = proc.stdout.readline()
        if not line:
            raise AssertionError(f"the Console driver closed its output while waiting for {what}")
        return line


class _Driver:
    def __init__(self, proc, port):
        self.proc, self.port = proc, port

    def probe(self) -> dict:
        self.proc.stdin.write("probe\n")
        self.proc.stdin.flush()
        while True:
            line = _readline(self.proc, timeout=60, what="a PROBE reply")
            if line.startswith("PROBE "):
                return json.loads(line[len("PROBE "):])


@pytest.fixture()
def console_process(tmp_path):
    """A real Console, in its own process, with its own store."""
    db = tmp_path / "console.db"
    SqliteStore(str(db)).close()
    script = tmp_path / "console_driver.py"
    script.write_text(_DRIVER.format(pkg_parent=PKG_PARENT))
    env = dict(os.environ, TC_CONSOLE_TOKEN="seam-test-token", TC_DB_PATH=str(db),
               PYTHONUNBUFFERED="1")
    proc = subprocess.Popen([sys.executable, str(script)], env=env, text=True,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        first = _readline(proc, timeout=60, what="the Console driver's port")
        assert first.startswith("PORT "), f"the Console driver did not start: {first!r}"
        yield _Driver(proc, int(first.split()[1])), db
    finally:
        try:
            proc.stdin.write("quit\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001 - teardown must not mask a test failure
            proc.kill()


#: Every HTTP call here is bounded. An unbounded urlopen against a server that never answers would
#: hang the whole suite instead of failing this one test.
_HTTP_TIMEOUT = 30


def _opener(port: int):
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open(urllib.request.Request(f"http://127.0.0.1:{port}/login",
                                       data=b"token=seam-test-token", method="POST"),
                timeout=_HTTP_TIMEOUT)
    return opener


def _read(opener, url: str, *, data: bytes | None = None, headers: dict | None = None) -> str:
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers=headers or {})
    try:
        return opener.open(request, timeout=_HTTP_TIMEOUT).read().decode()
    except urllib.error.HTTPError as exc:      # 403/404 are answers, not test failures
        return exc.read().decode()


def test_a_console_process_cannot_select_a_deployment_target_after_serving(console_process):
    """The milestone's criterion 2, executed rather than asserted about source.

    Before the Console has served anything the process CAN open the gate — that control is what
    makes the second half meaningful. One real HTTP request later it cannot, and no request field,
    query string, header or cookie has moved the resolved target off production.
    """
    driver, db = console_process

    before = driver.probe()
    assert before["gate"] == "open", (
        "control failed: this process could not open the gate even before serving, so the "
        f"post-request refusal would prove nothing ({before['gate']})")
    assert before["built"] == "built"
    assert before["latched"] is False

    # A planned run so the deploy pages have real content to render.
    store = SqliteStore(str(db))
    plan = deploy.build_plan(SHA)
    run_id = store.plan_deploy(sha=SHA, plan=plan, plan_digest=deploy.plan_digest(plan),
                               requested_by="owner")
    store.close()

    opener = _opener(driver.port)
    query = urllib.parse.urlencode(_INJECTIONS)
    body = urllib.parse.urlencode({**_INJECTIONS, "sha": SHA, "csrf": "x"}).encode()
    headers = {"X-Deploy-Target": "injected", "X-Forwarded-Target": "/tmp/injected/app",
               "Cookie": "tc_deploy_target=injected"}
    pages = [
        _read(opener, f"http://127.0.0.1:{driver.port}/deploy?{query}"),
        _read(opener, f"http://127.0.0.1:{driver.port}/deploy/{run_id}?{query}"),
        _read(opener, f"http://127.0.0.1:{driver.port}/deploy?{query}", headers=headers),
        _read(opener, f"http://127.0.0.1:{driver.port}/deploy/plan", data=body, headers=headers),
        _read(opener, f"http://127.0.0.1:{driver.port}/deploy/{run_id}/start", data=body),
    ]

    after = driver.probe()
    assert after["latched"] is True
    assert after["gate"].startswith("refused:"), after["gate"]
    assert after["built"].startswith("refused:"), after["built"]
    assert after["resolved"] == "production"
    assert after["resolved_app_dir"] == deploy_target.PRODUCTION.app_dir

    for page in pages:
        for injected in ("/tmp/injected", "tc-console-injected", "tc-deploy-injected",
                         "disposable/injected"):
            assert injected not in page, f"the Console reflected {injected!r} back"

    # And nothing was recorded under an injected target.
    store = SqliteStore(str(db))
    try:
        rows = store.list_deploy_runs()
        assert len(rows) == 1 and rows[0]["id"] == run_id
        assert json.loads(rows[0]["plan"])["target"] == "production"
        assert json.loads(rows[0]["plan"])["repository"] == deploy_target.PRODUCTION.app_dir
    finally:
        store.close()


def test_binding_the_console_latches_the_seam_before_a_single_request(monkeypatch):
    """`serve()` latches before it binds, so a Console nobody has talked to yet — or one whose
    bind fails — is already unable to select a target. The real `serve()` runs; only the handle
    needed to stop it again afterwards is captured."""
    monkeypatch.setenv(console._TOKEN_ENV, "seam-latch-token")
    assert deploy_target.http_boundary_latched() is False

    servers = []
    real_server = console.ThreadingHTTPServer
    monkeypatch.setattr(console, "ThreadingHTTPServer",
                        lambda *a, **kw: servers.append(real_server(*a, **kw)) or servers[-1])
    thread = threading.Thread(target=lambda: console.serve(port=0), daemon=True)
    thread.start()
    try:
        # Wait for the SERVER OBJECT, not just the latch. The latch is set before the bind — that
        # is the property under test — so waiting on it alone can win the race and leave `servers`
        # empty, and then teardown shuts nothing down and blocks on a join that never comes.
        deadline = time.time() + 10
        while time.time() < deadline and not servers:
            time.sleep(0.02)
        assert servers, "console.serve never constructed its server"
        assert deploy_target.http_boundary_latched() is True
        with pytest.raises(deploy.DeployRefused):
            deploy_target.open_cli_target_gate()
    finally:
        for server in servers:
            server.shutdown()
        thread.join(timeout=10)
        assert not thread.is_alive(), "console.serve did not return after shutdown"


def test_the_console_never_calls_the_seam_mutators():
    """A supporting check, and labelled as one: it reads source, so it can only corroborate the
    executed proof above. Its value is catching a FUTURE handler that reaches for the seam."""
    import ast

    for module in ("console.py", "console_views.py"):
        path = os.path.join(os.path.dirname(deploy.__file__), module)
        for node in ast.walk(ast.parse(open(path).read())):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                assert not name.endswith(("open_cli_target_gate", "make_disposable_target")), \
                    f"{module} calls {name}: the Console must never select a deployment target"


# --- an authorization is bound to the target it was given for ----------------------------------

def test_a_plan_authorized_for_one_target_cannot_be_executed_against_another(tmp_path,
                                                                             monkeypatch):
    """Without this, a plan reviewed for the disposable target could run against production just
    by executing it in a different process: the SHA and the digest would still match."""
    monkeypatch.setenv("TC_DB_PATH", str(tmp_path / "store.db"))
    deploy_target.open_cli_target_gate()
    disposable = deploy_target.make_disposable_target(**_disposable_fields(tmp_path))
    store = SqliteStore(str(tmp_path / "store.db"))
    try:
        plan = deploy.build_plan(SHA, target=disposable)
        run_id = store.plan_deploy(sha=SHA, plan=plan, plan_digest=deploy.plan_digest(plan),
                                   requested_by="harness")
        with pytest.raises(deploy.DeployRefused) as exc:
            deploy.execute(store, run_id, context={},          # {} means production
                           executors={s.name: (lambda sha, ctx: deploy.StepResult(True, "ok"))
                                      for s in deploy.STEPS})
        assert "authorized for target 'probe'" in str(exc.value)
        assert store.get_deploy_run(run_id)["status"] == "planned"
        assert store.list_deploy_steps(run_id) == []
    finally:
        store.close()


def test_the_target_name_is_part_of_what_the_owner_authorizes(tmp_path):
    deploy_target.open_cli_target_gate()
    disposable = deploy_target.make_disposable_target(**_disposable_fields(tmp_path))
    production_plan = deploy.build_plan(SHA)
    disposable_plan = deploy.build_plan(SHA, target=disposable)
    assert deploy.plan_digest(production_plan) != deploy.plan_digest(disposable_plan)
    assert "deployment target ...... production" in deploy.plan_text(production_plan)
    assert "deployment target ...... probe" in deploy.plan_text(disposable_plan)
    assert re.search(r"deployment target \.+ production \(plan predates the target seam\)",
                     deploy.plan_text({**production_plan, "target": None}))


# --- production's remaining environment influence is bounded, and said to be bounded ------------

def test_a_production_override_outside_the_allowlist_is_refused(monkeypatch):
    """`TC_DB_PATH` and `TC_VENV` still configure the production run — removing them would point a
    real deployment at the wrong store. They are now bounded: an override must land inside the
    target's own allowlist. This is a tightening, NOT the constructed-environment property that
    criterion 5 asks of the privileged program, which is not built yet."""
    monkeypatch.setenv("TC_DB_PATH", "/tmp/somewhere-else/store.db")
    with pytest.raises(deploy.DeployRefused):
        deploy.context_for(deploy_target.PRODUCTION)

    monkeypatch.setenv("TC_DB_PATH", deploy_target.PRODUCTION.db_path)
    monkeypatch.setenv("TC_VENV", "/opt/tc_ai_growth/app/orchestrator/../../../etc")
    with pytest.raises(deploy.DeployRefused):
        deploy.context_for(deploy_target.PRODUCTION)


def test_a_disposable_context_reads_no_environment_at_all(tmp_path, monkeypatch):
    monkeypatch.setenv("TC_DB_PATH", "/tmp/inherited/store.db")
    monkeypatch.setenv("TC_VENV", "/tmp/inherited/venv")
    deploy_target.open_cli_target_gate()
    target = deploy_target.make_disposable_target(**_disposable_fields(tmp_path))
    ctx = deploy.context_for(target)
    assert ctx["db_path"] == target.db_path
    assert ctx["venv"] == target.venv
    assert "/tmp/inherited" not in json.dumps(ctx, default=str)
    assert ctx["child_env"]["TC_DB_PATH"] == target.db_path
    assert "PYTHONPATH" not in ctx["child_env"]
