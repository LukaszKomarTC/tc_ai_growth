#!/bin/bash
# WP-U4d — the ONE root-privileged program of the governed deployment runner.
#
# Auditable source: this file, in-repository. Installed by scripts/install-tc-deploy.sh to
# /usr/local/bin/tc-deploy-release.sh as root:root 0755, and permitted to the service user by
# exactly one sudoers rule. The repository copy is the source of truth; the installer records a
# digest so the installed copy can be checked against what was reviewed.
#
# ---------------------------------------------------------------------------------------------
# THE RULE (PR #79, review rounds 1 and 2):
#
#   Root executes ONLY root-owned code, and trusts NOTHING the caller can influence.
#
# Round 1 removed the no-op `sudo -u tcgrowth` calls. Round 2 found that this wrapper still
# exec'd deploy-console.sh from the release worktree, which `tcgrowth` owns and can rewrite after
# checkout — `git rev-parse HEAD` proves which commit was checked out, not that the files still
# match it, and git cannot be the witness because the worktree's .git is writable by the same
# account. Round 3 (this version) closes the remaining gap: the privileged machinery is a
# root-owned copy verified by digest, and every input is re-derived here rather than accepted.
#
# The caller sets environment variables. THEY ARE IGNORED. Everything below is a constant or is
# derived from the single validated SHA. The child is started with a constructed minimal
# environment, so nothing the service user exported can reach it.
# ---------------------------------------------------------------------------------------------

set -euo pipefail

# ------------------------------------------------------------------ root-owned constants only
ROOT_LIB=/usr/local/lib/tc-deploy
DEPLOY_SCRIPT="$ROOT_LIB/deploy-console.sh"
MANIFEST="$ROOT_LIB/MANIFEST.sha256"

RELEASES_DIR=/opt/tc_ai_growth/releases
APP_DIR=/opt/tc_ai_growth/app
VENV="$APP_DIR/orchestrator/.venv"
STORE_DB="$APP_DIR/orchestrator/data/tc_growth.db"
SERVICE_USER=tcgrowth
SERVICE_NAME=tc-console
BACKUP_DIR=/var/backups/tc-console

die() { printf 'tc-deploy-release: %s\n' "$1" >&2; exit 2; }

# A root-owned path must be owned by root and writable by nobody else. Checked at EVERY
# invocation, not trusted from install time: if the mode or owner was loosened since, this is
# where the deployment stops.
assert_root_owned() {
    local path="$1" kind="$2" meta
    [ -e "$path" ] || die "missing root-owned $kind: $path (run scripts/install-tc-deploy.sh)"
    meta="$(stat -c '%U:%G %a' "$path")"
    case "$meta" in
        "root:root "[0-7][0-57][0-57]) ;;
        *) die "$path must be root:root and not group/other writable (found: $meta)" ;;
    esac
}

# The parent directory matters as much as the file: a writable directory means the file can be
# replaced wholesale, whatever its own mode says.
assert_root_owned "$ROOT_LIB" "directory"
assert_root_owned "$DEPLOY_SCRIPT" "helper"
assert_root_owned "$MANIFEST" "manifest"

# The installed helper must still be the reviewed one. The manifest is root-owned, so an
# unprivileged account can neither swap the helper nor update the digest that would betray it.
( cd "$ROOT_LIB" && sha256sum --check --status "$MANIFEST" ) \
    || die "installed helper does not match its recorded digest — refusing to run it"

# ------------------------------------------------------------------ fixed verbs only
[ "$#" -ge 1 ] || die "usage: tc-deploy-release.sh apply <40-hex-sha> | rollback"
VERB="$1"
shift

case "$VERB" in
    apply)
        [ "$#" -eq 1 ] || die "apply takes exactly one argument (a 40-hex commit SHA), got $#"
        SHA="$1"
        case "$SHA" in *[!0-9a-f]* | "") die "not a lowercase 40-hex commit SHA" ;; esac
        [ "${#SHA}" -eq 40 ] || die "not a lowercase 40-hex commit SHA (length ${#SHA})"

        REL="$RELEASES_DIR/$SHA"
        [ -d "$REL" ] || die "no release worktree at $REL — this program never creates one"

        # Sanity only. Explicitly NOT a content-integrity or clean-worktree guarantee: the tree
        # and its .git belong to the service user. The integrity control is that root runs the
        # digest-verified helper, never anything from $REL.
        HEAD="$(git -C "$REL" rev-parse HEAD 2>/dev/null || true)"
        [ "$HEAD" = "$SHA" ] || die "release worktree HEAD ($HEAD) is not the requested SHA"

        # Constructed minimal environment. Whatever the caller exported is discarded; every value
        # below is a constant of this file or derived from the validated SHA.
        exec /usr/bin/env -i \
            PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
            HOME=/root \
            TC_RELEASE_DIR="$REL" \
            TC_RELEASE_SHA="$SHA" \
            TC_VENV="$VENV" \
            TC_STORE_DB="$STORE_DB" \
            TC_SERVICE_USER="$SERVICE_USER" \
            TC_SERVICE_NAME="$SERVICE_NAME" \
            TC_BACKUP_DIR="$BACKUP_DIR" \
            "$DEPLOY_SCRIPT" --apply
        ;;
    rollback)
        [ "$#" -eq 0 ] || die "rollback takes no arguments — there is nothing to choose"
        # Rollback restores the previous snapshot from $BACKUP_DIR, which is root-owned. It does
        # NOT read systemd's WorkingDirectory to find code: that path points into a
        # service-user-writable worktree, and using it to select an executable would reintroduce
        # exactly the defect this program exists to prevent.
        assert_root_owned "$BACKUP_DIR" "snapshot directory"
        exec /usr/bin/env -i \
            PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
            HOME=/root \
            TC_SERVICE_NAME="$SERVICE_NAME" \
            TC_BACKUP_DIR="$BACKUP_DIR" \
            "$DEPLOY_SCRIPT" --rollback
        ;;
    *)
        die "unknown verb '$VERB' — only 'apply' and 'rollback' exist"
        ;;
esac
