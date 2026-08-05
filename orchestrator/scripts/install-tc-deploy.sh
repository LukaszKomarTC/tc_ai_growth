#!/bin/bash
# WP-U4d — deterministic host install of the privileged deployment machinery (PR #79, round 2).
#
# Run ONCE by the owner, as root, from a reviewed checkout. Not run by the deployment runner and
# not reachable from the Console: updating the machinery that performs deployments is a deliberate
# host action with its own review, because the thing that performs deployments must not be
# silently replaceable by a deployment.
#
#   sudo ./scripts/install-tc-deploy.sh
#
# It installs exactly two files, root-owned, and records a digest manifest so the privileged
# program can verify at every invocation that the installed helper is still the reviewed one:
#
#   /usr/local/bin/tc-deploy-release.sh        root:root 0755   (the sudoers entry point)
#   /usr/local/lib/tc-deploy/deploy-console.sh root:root 0755   (the privileged helper)
#   /usr/local/lib/tc-deploy/MANIFEST.sha256   root:root 0644   (digest of the helper)

set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_LIB=/usr/local/lib/tc-deploy
ROOT_BIN=/usr/local/bin
SERVICE_USER=tcgrowth

die() { printf 'install-tc-deploy: %s\n' "$1" >&2; exit 2; }

[ "$(id -u)" -eq 0 ] || die "must run as root"

for f in tc-deploy-release.sh deploy-console.sh; do
    [ -f "$SRC_DIR/$f" ] || die "missing source file: $SRC_DIR/$f"
done

# --- BEGIN shared permission predicate (byte-identical in tc-deploy-release.sh and
# install-tc-deploy.sh; tests assert they have not drifted) ---
# Refuse any path carrying a group- or other-write bit.
#
# Implemented as a NUMERIC MASK, not a glob. The first version of this guard used
# "root:root "[0-7][0-57][0-57], and a shell character range cannot express "no write bit":
# [0-57] is the set {0,1,2,3,4,5,7}, so it accepted 2, 3 and 7 — every one of them writable.
# 0777 passed a check whose own error message said "not group/other writable" (PR #79 round 3).
mode_has_write_bits() {
    # $1 is an octal mode from `stat -c %a`, 3 or 4 digits. 8#22 is g+w | o+w.
    local mode="$1"
    [ -n "$mode" ] || return 0            # unreadable mode => treat as unsafe
    case "$mode" in *[!0-7]*) return 0 ;; esac   # not octal => unsafe
    (( 8#$mode & 8#22 ))
}
# --- END shared permission predicate ---

# A root-owned file inside a directory someone else can write is not protected: the file can be
# replaced wholesale. Refuse to install into an unsafe parent rather than produce a surface that
# only looks locked down.
assert_safe_dir() {
    local dir="$1" owner mode
    [ -d "$dir" ] || return 0
    owner="$(stat -c '%U:%G' "$dir")"
    [ "$owner" = "root:root" ] || die "$dir must be root:root (found: $owner)"
    mode="$(stat -c '%a' "$dir")"
    if mode_has_write_bits "$mode"; then
        die "$dir is group- or other-writable (mode $mode) — refusing to install into it"
    fi
}

assert_safe_dir /usr/local
assert_safe_dir /usr/local/lib
assert_safe_dir "$ROOT_BIN"

install -d -o root -g root -m 0755 "$ROOT_LIB"
assert_safe_dir "$ROOT_LIB"

install -o root -g root -m 0755 "$SRC_DIR/deploy-console.sh"   "$ROOT_LIB/deploy-console.sh"
install -o root -g root -m 0755 "$SRC_DIR/tc-deploy-release.sh" "$ROOT_BIN/tc-deploy-release.sh"

# The manifest is what the privileged program checks on every run. Root-owned, so the service
# user can neither swap the helper nor rewrite the digest that would betray the swap.
( cd "$ROOT_LIB" && sha256sum deploy-console.sh > MANIFEST.sha256 )
chown root:root "$ROOT_LIB/MANIFEST.sha256"
chmod 0644 "$ROOT_LIB/MANIFEST.sha256"

# Verify what actually landed, rather than assuming the copies succeeded.
( cd "$ROOT_LIB" && sha256sum --check --status MANIFEST.sha256 ) \
    || die "post-install digest verification FAILED"

src_digest="$(sha256sum < "$SRC_DIR/deploy-console.sh" | cut -d' ' -f1)"
inst_digest="$(sha256sum < "$ROOT_LIB/deploy-console.sh" | cut -d' ' -f1)"
[ "$src_digest" = "$inst_digest" ] || die "installed helper differs from the reviewed source"

printf 'installed:\n'
printf '  %s\n' "$ROOT_BIN/tc-deploy-release.sh"
printf '  %s  (sha256 %s)\n' "$ROOT_LIB/deploy-console.sh" "${inst_digest:0:16}…"
printf '  %s\n' "$ROOT_LIB/MANIFEST.sha256"
printf '\nAdd exactly this sudoers entry (visudo -f /etc/sudoers.d/tc-console-deploy):\n'
printf '  %s ALL=(root) NOPASSWD: %s\n' "$SERVICE_USER" "$ROOT_BIN/tc-deploy-release.sh"
printf '\nThe deployment operation stays disabled until the disposable proof passes (issue #77).\n'
