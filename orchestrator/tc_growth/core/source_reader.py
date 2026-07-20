"""Source Reader core (WP-07): path resolution + deny rules. Pure logic, no tool wiring.

Trust model: the orchestrator is co-located with both sites, so source access is plain
filesystem reads — no FTP, no network credentials. Safety therefore lives entirely in path
discipline:

- ALLOWLIST: only the profile-configured roots (wp-content/plugins, themes, mu-plugins,
  selected logs) are reachable at all.
- CANONICALIZE FIRST: every candidate path is resolved (symlinks followed, `..` collapsed)
  BEFORE any check — a symlink inside a root pointing outside it dies here.
- DENY-LIST WINS: even inside a root, credential-bearing and bulk-data files are unreadable:
  wp-config.php, .env*, SQL dumps, archives, key material, anything under uploads/.

"Read-only" prevents mutation; these rules prevent information exposure — the two are
different properties and both are enforced (WP-07 spec).
"""

from __future__ import annotations

from pathlib import Path

MAX_READ_BYTES = 256 * 1024  # per-file cap; truncated reads carry an explicit marker
MAX_LIST_ENTRIES = 500

_DENY_SUFFIXES = {".sql", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".pem", ".key", ".p12", ".pfx"}
_DENY_BASENAMES = {"wp-config.php", ".htpasswd", "auth.json", "id_rsa", "id_ed25519"}
_DENY_COMPONENTS = {"uploads", "backups", "backup", ".ssh", "secrets"}
_DENY_SUBSTRINGS = ("credential", "password")  # in the basename


class SourceAccessDenied(Exception):
    """Raised when a path fails allowlist or deny rules. The message is safe to show."""


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


def resolve_checked(candidate: str, roots: list[Path]) -> Path:
    """Canonicalize `candidate` and enforce allowlist + deny rules. Returns the resolved path
    or raises SourceAccessDenied. Deny rules run on the RESOLVED path, so symlink names cannot
    smuggle a denied target past the checks."""
    if not roots:
        raise SourceAccessDenied("source reader not configured for this profile (TC_SOURCE_ROOTS)")

    resolved = Path(candidate).resolve()

    if not any(resolved == r or r in resolved.parents for r in roots):
        raise SourceAccessDenied(f"path outside allowlisted roots: {resolved}")

    name = resolved.name.lower()
    if name in _DENY_BASENAMES or name.startswith(".env"):
        raise SourceAccessDenied(f"denied file: {resolved.name}")
    if resolved.suffix.lower() in _DENY_SUFFIXES:
        raise SourceAccessDenied(f"denied file type: {resolved.suffix}")
    if any(part.lower() in _DENY_COMPONENTS for part in resolved.parts):
        raise SourceAccessDenied(f"denied directory in path: {resolved}")
    if any(s in name for s in _DENY_SUBSTRINGS):
        raise SourceAccessDenied(f"denied filename pattern: {resolved.name}")

    return resolved


def read_file(resolved: Path, *, max_bytes: int = MAX_READ_BYTES) -> dict:
    """Read a checked path, capped. Binary-safe: decoded with replacement so a stray binary
    can't crash a run; the caller sees sizes and an explicit truncation flag."""
    if not resolved.is_file():
        raise SourceAccessDenied(f"not a readable file: {resolved}")
    size = resolved.stat().st_size
    with open(resolved, "rb") as fh:
        blob = fh.read(max_bytes)
    return {
        "path": str(resolved),
        "size_bytes": size,
        "returned_bytes": len(blob),
        "truncated": size > len(blob),
        "content": blob.decode("utf-8", errors="replace"),
    }


def list_dir(resolved: Path, *, max_entries: int = MAX_LIST_ENTRIES) -> dict:
    """List a checked directory (one level, sorted, capped). Denied children are shown as
    entries but marked unreadable — visibility of the tree is fine; their content is not."""
    if not resolved.is_dir():
        raise SourceAccessDenied(f"not a directory: {resolved}")
    entries = []
    for child in sorted(resolved.iterdir(), key=lambda p: p.name)[:max_entries]:
        entry = {
            "name": child.name,
            "type": "dir" if child.is_dir() else "file",
            "size_bytes": child.stat().st_size if child.is_file() else None,
        }
        try:
            resolve_checked(str(child), [resolved])
        except SourceAccessDenied:
            entry["readable"] = False
        entries.append(entry)
    return {"path": str(resolved), "entries": entries,
            "truncated": len(list(resolved.iterdir())) > max_entries}
