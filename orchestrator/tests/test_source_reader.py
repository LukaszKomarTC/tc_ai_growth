"""WP-07 Source Reader: path discipline is the entire safety model — test it adversarially.

Spec acceptance under test: traversal/symlink escapes rejected; deny-list wins over allowlist
in every case; size caps enforced with explicit truncation; reads audit-logged (metadata only);
unconfigured profile fails closed; budget bounds runaway loops.
"""

from __future__ import annotations

import json

import pytest

from tc_growth.core.approval import Phase, is_tool_allowed, needs_confirmation
from tc_growth.core.source_reader import (
    SourceAccessDenied,
    list_dir,
    parse_roots,
    read_file,
    resolve_checked,
)
from tc_growth.tools.load import load_all


@pytest.fixture()
def root(tmp_path):
    plugins = tmp_path / "wp-content" / "plugins"
    (plugins / "some-plugin").mkdir(parents=True)
    (plugins / "some-plugin" / "main.php").write_text("<?php // plugin code")
    return plugins


def test_unconfigured_profile_fails_closed():
    with pytest.raises(SourceAccessDenied, match="not configured"):
        resolve_checked("/etc/passwd", [])


def test_path_outside_roots_rejected(root, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("nope")
    with pytest.raises(SourceAccessDenied, match="outside allowlisted"):
        resolve_checked(str(outside), [root])
    with pytest.raises(SourceAccessDenied, match="outside allowlisted"):
        resolve_checked(str(root / ".." / ".." / "outside.txt"), [root])  # dot-dot traversal


def test_symlink_escape_dies_at_canonicalization(root, tmp_path):
    secret = tmp_path / "wp-config.php"
    secret.write_text("<?php define('DB_PASSWORD', 'x');")
    link = root / "innocent-looking.php"
    link.symlink_to(secret)
    with pytest.raises(SourceAccessDenied):  # resolved target is outside root AND a denied name
        resolve_checked(str(link), [root])


def test_deny_list_wins_inside_allowlisted_roots(root):
    cases = {
        "wp-config.php": "<?php",         # credential file
        ".env": "SECRET=1",               # env file
        ".env.local": "SECRET=1",
        "dump.sql": "INSERT ...",         # bulk data
        "backup.tar.gz": "...",           # archive (suffix .gz)
        "server.key": "...",              # key material
        "my-credentials.txt": "...",      # substring rule
    }
    for name, content in cases.items():
        f = root / name
        f.write_text(content)
        with pytest.raises(SourceAccessDenied):
            resolve_checked(str(f), [root])
    up = root / "uploads" / "export.csv"
    up.parent.mkdir()
    up.write_text("data")
    with pytest.raises(SourceAccessDenied, match="denied directory"):
        resolve_checked(str(up), [root])


def test_allowed_read_returns_content_and_caps_size(root):
    ok = resolve_checked(str(root / "some-plugin" / "main.php"), [root])
    out = read_file(ok, [root])
    assert out["content"].startswith("<?php") and out["truncated"] is False

    big = root / "some-plugin" / "big.php"
    big.write_bytes(b"x" * (300 * 1024))
    out = read_file(resolve_checked(str(big), [root]), [root])
    assert out["truncated"] is True and out["returned_bytes"] == 256 * 1024
    assert out["size_bytes"] == 300 * 1024  # caller sees the real size


def test_list_marks_denied_children_unreadable(root):
    (root / "wp-config.php").write_text("<?php")
    out = list_dir(resolve_checked(str(root), [root]), [root])
    by_name = {e["name"]: e for e in out["entries"]}
    assert "[redacted:secret_name]" in by_name                 # present but name withheld
    assert by_name["[redacted:secret_name]"]["readable"] is False
    assert "wp-config.php" not in by_name                      # the name itself never leaks
    assert "readable" not in by_name["some-plugin"]            # ordinary entries unmarked


def test_parse_roots_drops_nonexistent_silently(root):
    roots = parse_roots(f"{root}:/does/not/exist:")
    assert roots == [root.resolve()]


def test_tools_registered_read_only_and_budget_enforced(root, tmp_path, monkeypatch):
    names = {t.name for t in load_all().all()}
    assert {"source_read", "source_list"} <= names
    for name in ("source_read", "source_list"):
        assert is_tool_allowed(name, Phase.READ_ONLY)
        assert not needs_confirmation(name)

    import tc_growth.tools.source_reader as sr
    monkeypatch.setenv("TC_SOURCE_ROOTS", str(root))
    monkeypatch.setattr(sr, "_roots", lambda: [root.resolve()])
    monkeypatch.setattr(sr, "BASE_DIR", tmp_path)          # audit lands in tmp
    monkeypatch.setattr(sr, "_budgets", {})

    out = sr._read({"path": str(root / "some-plugin" / "main.php")})
    assert out["content"].startswith("<?php")

    audit = (tmp_path / "data" / "source_audit.jsonl").read_text().strip().splitlines()
    rec = json.loads(audit[-1])
    assert rec["action"] == "read" and rec["outcome"] == "ok" and rec["bytes"] > 0
    assert "content" not in rec                            # metadata only, never file content

    monkeypatch.setattr(sr, "_budgets", {sr._budget_key(): {"calls": 10**6, "bytes": 0}})
    from tc_growth.tools.base import ToolError
    with pytest.raises(ToolError, match="budget exhausted"):
        sr._read({"path": str(root / "some-plugin" / "main.php")})


def test_denied_read_is_audited_as_denied(root, tmp_path, monkeypatch):
    import tc_growth.tools.source_reader as sr
    from tc_growth.tools.base import ToolError
    monkeypatch.setattr(sr, "_roots", lambda: [root.resolve()])
    monkeypatch.setattr(sr, "BASE_DIR", tmp_path)
    (root / "wp-config.php").write_text("<?php")
    with pytest.raises(ToolError):
        sr._read({"path": str(root / "wp-config.php")})
    rec = json.loads((tmp_path / "data" / "source_audit.jsonl").read_text().strip().splitlines()[-1])
    assert rec["outcome"].startswith("denied")


# --- Reviewer hardening round (TOCTOU, non-regular, reason codes, citation identity) ------

def test_read_rejects_fifo_and_directories(root):
    import os
    fifo = root / "some-plugin" / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(SourceAccessDenied) as exc:
        read_file(resolve_checked(str(fifo), [root]), [root])
    assert exc.value.code in ("not_regular", "symlink")
    with pytest.raises(SourceAccessDenied):
        read_file(resolve_checked(str(root / "some-plugin"), [root]), [root])


def test_expanded_deny_list_git_bak_npmrc(root):
    git_cfg = root / ".git" / "config"
    git_cfg.parent.mkdir()
    git_cfg.write_text("[remote]")
    for path in (git_cfg, root / "old-code.bak", root / ".npmrc"):
        if not path.exists():
            path.write_text("x")
        with pytest.raises(SourceAccessDenied) as exc:
            resolve_checked(str(path), [root])
        assert exc.value.code in ("denied_dir", "denied_type", "secret_name")


def test_denials_carry_stable_reason_codes(root, tmp_path):
    cases = {
        str(tmp_path / "outside.txt"): "outside_root",
        str(root / "wp-config.php"): "secret_name",
        str(root / "dump.sql"): "denied_type",
        str(root / "uploads" / "x.csv"): "denied_dir",
        str(root / "my-credentials.txt"): "secret_pattern",
    }
    (tmp_path / "outside.txt").write_text("x")
    for path, code in cases.items():
        with pytest.raises(SourceAccessDenied) as exc:
            resolve_checked(path, [root])
        assert exc.value.code == code, path


def test_read_result_carries_citation_identity(root):
    out = read_file(resolve_checked(str(root / "some-plugin" / "main.php"), [root]), [root])
    assert out["rel_path"] == "some-plugin/main.php" and out["root"] == str(root.resolve())
    assert len(out["returned_sha256"]) == 64 and out["mtime"] > 0 and out["mtime_ns"] > 0
    assert out["content_sha256"] == out["returned_sha256"]  # small file: full == returned
    assert out["lines_returned"][0] == 1 and out["binary"] is False


def test_binary_content_rejected_with_metadata_only(root):
    blob = root / "some-plugin" / "image.php"   # php suffix, binary body — suffix can lie
    blob.write_bytes(b"\x89PNG\x00\x01binary")
    out = read_file(resolve_checked(str(blob), [root]), [root])
    assert out["binary"] is True and out["content"] == ""
    assert out["returned_sha256"]                # identity still reported


def test_listing_redacts_leak_prone_names(root):
    (root / "customer-export-july.csv").write_text("a,b")
    (root / "stripe-token-backup.txt").write_text("x")
    out = list_dir(resolve_checked(str(root), [root]), [root])
    names = " ".join(e["name"] for e in out["entries"])
    assert "customer-export-july.csv" not in names
    assert "stripe-token-backup.txt" not in names
    assert "[redacted:" in names


# --- Reviewer round 3: hash semantics + run-scoped budget ---------------------------------

def test_dual_hash_semantics_on_truncated_file(root):
    """content_sha256 identifies the WHOLE file (streamed from the same verified fd);
    returned_sha256 identifies only the supplied evidence. On truncation they differ."""
    import hashlib
    big = root / "some-plugin" / "big2.php"
    data = b"a" * (256 * 1024) + b"b" * 1000    # 257KB: truncated, but under the hash cap
    big.write_bytes(data)
    out = read_file(resolve_checked(str(big), [root]), [root])
    assert out["truncated"] is True
    assert out["content_sha256"] == hashlib.sha256(data).hexdigest()
    assert out["returned_sha256"] == hashlib.sha256(data[:256 * 1024]).hexdigest()
    assert out["content_sha256"] != out["returned_sha256"]
    assert out["bytes_consumed"] == len(data)   # hashing bandwidth is accounted


def test_full_hash_capped_with_explicit_note(root, monkeypatch):
    import tc_growth.core.source_reader as core
    monkeypatch.setattr(core, "MAX_FULL_HASH_BYTES", 300 * 1024)
    huge = root / "some-plugin" / "huge.php"
    huge.write_bytes(b"x" * (400 * 1024))
    out = core.read_file(core.resolve_checked(str(huge), [root]), [root])
    assert out["content_sha256"] is None and "full-hash cap" in out["content_hash_note"]
    assert out["returned_sha256"]               # excerpt identity always present


def test_budget_is_keyed_per_run_and_profile(root, tmp_path, monkeypatch):
    """The lifecycle boundary is structural: (run, profile) key — a second run identity gets
    a fresh allowance; the same run cannot escape its own."""
    import tc_growth.tools.source_reader as sr
    from tc_growth.tools.base import ToolError
    monkeypatch.setattr(sr, "_roots", lambda: [root.resolve()])
    monkeypatch.setattr(sr, "BASE_DIR", tmp_path)
    monkeypatch.setattr(sr, "_budgets", {})
    target = str(root / "some-plugin" / "main.php")

    sr.bind_run("run-A")
    for _ in range(sr._READ_BUDGET):
        sr._read({"path": target})
    with pytest.raises(ToolError, match="budget exhausted"):
        sr._read({"path": target})

    sr.bind_run("run-B")                        # new run identity -> fresh allowance
    assert sr._read({"path": target})["returned_sha256"]
    sr.bind_run("run-A")                        # returning to A: still exhausted
    with pytest.raises(ToolError, match="budget exhausted"):
        sr._read({"path": target})
    sr._bound_run[0] = None                     # reset for other tests


def test_budget_exhaustion_is_audited_distinctly(root, tmp_path, monkeypatch):
    import tc_growth.tools.source_reader as sr
    from tc_growth.tools.base import ToolError
    monkeypatch.setattr(sr, "_roots", lambda: [root.resolve()])
    monkeypatch.setattr(sr, "BASE_DIR", tmp_path)
    monkeypatch.setattr(sr, "_budgets", {sr._budget_key(): {"calls": 10**6, "bytes": 0}})
    with pytest.raises(ToolError):
        sr._read({"path": str(root / "some-plugin" / "main.php")})
    lines = (tmp_path / "data" / "source_audit.jsonl").read_text().strip().splitlines()
    outcomes = [json.loads(l)["outcome"] for l in lines]
    assert "budget_exhausted" in outcomes       # distinguishable from policy denials
