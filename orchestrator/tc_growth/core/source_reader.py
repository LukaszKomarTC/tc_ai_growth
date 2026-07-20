"""Source Reader core (WP-07): path resolution + deny rules. Pure logic, no tool wiring.

Trust model: the orchestrator is co-located with both sites, so source access is plain
filesystem reads — no FTP, no network credentials. Safety therefore lives entirely in path
discipline:

- ALLOWLIST: only the profile-configured roots are reachable at all.
- CANONICALIZE FIRST: candidates are resolved (symlinks followed, `..` collapsed) BEFORE any
  check — a symlink inside a root pointing outside it dies here.
- CHECK AND OPEN ARE ONE OPERATION (TOCTOU hardening, reviewer 2026-07-20): the file is
  opened O_NOFOLLOW, fstat'd for regular-file-ness, and the OPENED descriptor's real path is
  re-verified inside the roots before a byte is read. The security property applies to the
  file actually read, not just the pathname checked beforehand.
- DENY-LIST WINS: even inside a root, credential-bearing and bulk-data files are unreadable,
  each denial carrying a stable reason code.

KNOWN LIMITATION (documented deliberately): a HARD LINK to a sensitive file placed inside an
approved root is not a symlink and canonicalizes inside the root — the deny-list and control
over who may create files under the roots are the defenses; the reader cannot detect it.

"Read-only" prevents mutation; these rules prevent information exposure — different
properties, both enforced.
"""

from __future__ import annotations

import hashlib
import os
import stat as stat_mod
from pathlib import Path

MAX_READ_BYTES = 256 * 1024  # per-file cap; truncated reads carry an explicit marker
MAX_LIST_ENTRIES = 500

_DENY_SUFFIXES = {".sql", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".pem", ".key",
                  ".p12", ".pfx", ".bak", ".old", ".orig", ".swp"}
_DENY_BASENAMES = {"wp-config.php", ".htpasswd", "auth.json", ".npmrc", "id_rsa",
                   "id_ed25519", "docker-compose.override.yml", "secrets.yml", "secrets.yaml"}
_DENY_COMPONENTS = {"uploads", "backups", "backup", ".ssh", "secrets", ".git", ".svn", "node_modules"}
_DENY_SUBSTRINGS = ("credential", "password", "service-account")  # in the basename
# Names whose mere presence in a LISTING can leak (customer exports, key backups): shown
# redacted. Broader than the read deny-list on purpose — display cost is near zero.
_REDACT_SUBSTRINGS = ("customer", "export", "backup", "dump", "secret", "credential",
                      "password", "token")


class SourceAccessDenied(Exception):
    """Raised when a path fails any rule. `code` is a stable machine-readable reason:
    not_configured | outside_root | secret_name | denied_type | denied_dir | secret_pattern |
    not_regular | symlink."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def parse_roots(configured: str) -> list[Path]:
    """Resolve the profile's colon-separated roots. Nonexistent entries are dropped silently —
    a profile may legitimately configure roots that exist only on the VPS."""
    roots = []
    for raw in (configured or "").split(":"):
        raw = raw.strip()
        if not raw:
            continue
        p = Path(raw)
        if p.is_dir():
            roots.append(p.resolve())
    return roots


def _within(path: Path, roots: list[Path]) -> bool:
    return any(path == r or r in path.parents for r in roots)


def _deny_reason(resolved: Path) -> tuple[str, str] | None:
    name = resolved.name.lower()
    if name in _DENY_BASENAMES or name.startswith(".env"):
        return ("secret_name", f"denied file: {resolved.name}")
    if name.endswith("~"):
        return ("denied_type", f"denied backup marker: {resolved.name}")
    if resolved.suffix.lower() in _DENY_SUFFIXES:
        return ("denied_type", f"denied file type: {resolved.suffix}")
    if any(part.lower() in _DENY_COMPONENTS for part in resolved.parts):
        return ("denied_dir", f"denied directory in path: {resolved}")
    if any(s in name for s in _DENY_SUBSTRINGS):
        return ("secret_pattern", f"denied filename pattern: {resolved.name}")
    return None


def resolve_checked(candidate: str, roots: list[Path]) -> Path:
    """Canonicalize `candidate` and enforce allowlist + deny rules on the RESOLVED path, so a
    symlink's innocent name cannot smuggle a denied target past the checks."""
    if not roots:
        raise SourceAccessDenied("not_configured",
                                 "source reader not configured for this profile (TC_SOURCE_ROOTS)")
    resolved = Path(candidate).resolve()
    if not _within(resolved, roots):
        raise SourceAccessDenied("outside_root", f"path outside allowlisted roots: {resolved}")
    reason = _deny_reason(resolved)
    if reason:
        raise SourceAccessDenied(*reason)
    return resolved


def read_file(resolved: Path, roots: list[Path], *, max_bytes: int = MAX_READ_BYTES) -> dict:
    """TOCTOU-hardened read: open O_NOFOLLOW, reject non-regular files on the DESCRIPTOR,
    re-verify the opened file's real path, then read from that same descriptor.

    Result carries citation identity (reviewer 2026-07-20): relative path + owning root,
    sha256 of the returned bytes, mtime, and the returned line range — so a report citation
    like `file.php:L1-L146` traces to a specific content version, not just a pathname.
    Binary content (NUL byte) is rejected with metadata, never decoded blind."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(resolved), flags)
    except OSError as exc:
        code = "symlink" if getattr(exc, "errno", None) == getattr(os, "ELOOP", 40) else "not_regular"
        raise SourceAccessDenied(code, f"cannot open safely: {resolved.name} ({exc.strerror})")
    try:
        st = os.fstat(fd)
        if not stat_mod.S_ISREG(st.st_mode):
            raise SourceAccessDenied("not_regular", f"not a regular file: {resolved.name}")
        # Verify what we ACTUALLY opened (the descriptor), not what we checked earlier.
        fd_path = Path(f"/proc/self/fd/{fd}")
        if fd_path.exists():
            actual = Path(os.path.realpath(fd_path))
            if not _within(actual, roots):
                raise SourceAccessDenied("outside_root",
                                         f"opened file resolved outside roots: {actual}")
            reason = _deny_reason(actual)
            if reason:
                raise SourceAccessDenied(*reason)
        chunks, remaining = [], max_bytes
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        blob = b"".join(chunks)
    finally:
        os.close(fd)

    root = next((r for r in roots if r in resolved.parents or resolved == r), None)
    base = {
        "path": str(resolved),
        "root": str(root) if root else None,
        "rel_path": str(resolved.relative_to(root)) if root else resolved.name,
        "size_bytes": st.st_size,
        "returned_bytes": len(blob),
        "truncated": st.st_size > len(blob),
        "sha256_returned": hashlib.sha256(blob).hexdigest(),
        "mtime": st.st_mtime,
    }
    if b"\x00" in blob:
        return {**base, "binary": True, "content": "",
                "note": "binary content rejected — metadata only"}
    text = blob.decode("utf-8", errors="replace")
    return {**base, "binary": False, "content": text,
            "lines_returned": [1, text.count("\n") + (0 if text.endswith("\n") else 1)]}


def list_dir(resolved: Path, roots: list[Path], *, max_entries: int = MAX_LIST_ENTRIES) -> dict:
    """List a checked directory (one level, sorted, capped). Denied children are visible but
    marked unreadable WITH a reason code; names matching leak-prone patterns are REDACTED —
    'cannot read content' is not the same as 'safe to expose metadata' (reviewer 2026-07-20)."""
    if not resolved.is_dir():
        raise SourceAccessDenied("not_regular", f"not a directory: {resolved}")
    children = sorted(resolved.iterdir(), key=lambda p: p.name)
    entries = []
    for child in children[:max_entries]:
        entry: dict = {"type": "dir" if child.is_dir() else "file"}
        try:
            entry["size_bytes"] = child.stat().st_size if child.is_file() else None
        except OSError:
            entry["size_bytes"] = None
        deny = _deny_reason(child)
        lname = child.name.lower()
        if any(s in lname for s in _REDACT_SUBSTRINGS) or (
                deny and deny[0] in ("secret_name", "secret_pattern")):
            entry["name"] = f"[redacted:{deny[0] if deny else 'leak_prone_name'}]"
            entry["readable"] = False
        else:
            entry["name"] = child.name
            if deny:
                entry["readable"] = False
                entry["reason"] = deny[0]
        entries.append(entry)
    return {"path": str(resolved), "entries": entries, "truncated": len(children) > max_entries}
