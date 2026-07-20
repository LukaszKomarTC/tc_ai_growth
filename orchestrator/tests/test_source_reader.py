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
    out = read_file(ok)
    assert out["content"].startswith("<?php") and out["truncated"] is False

    big = root / "some-plugin" / "big.php"
    big.write_bytes(b"x" * (300 * 1024))
    out = read_file(resolve_checked(str(big), [root]))
    assert out["truncated"] is True and out["returned_bytes"] == 256 * 1024
    assert out["size_bytes"] == 300 * 1024  # caller sees the real size


def test_list_marks_denied_children_unreadable(root):
    (root / "wp-config.php").write_text("<?php")
    out = list_dir(resolve_checked(str(root), [root]))
    by_name = {e["name"]: e for e in out["entries"]}
    assert by_name["wp-config.php"].get("readable") is False   # visible, not readable
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
    monkeypatch.setattr(sr, "_spent", {"calls": 0, "bytes": 0})

    out = sr._read({"path": str(root / "some-plugin" / "main.php")})
    assert out["content"].startswith("<?php")

    audit = (tmp_path / "data" / "source_audit.jsonl").read_text().strip().splitlines()
    rec = json.loads(audit[-1])
    assert rec["action"] == "read" and rec["outcome"] == "ok" and rec["bytes"] > 0
    assert "content" not in rec                            # metadata only, never file content

    monkeypatch.setattr(sr, "_spent", {"calls": 10**6, "bytes": 0})
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
