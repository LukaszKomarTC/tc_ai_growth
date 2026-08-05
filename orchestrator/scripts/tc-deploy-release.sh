#!/bin/bash
# WP-U4d — the ONLY root-privileged entry point of the governed deployment runner.
#
# Installed root-owned at /usr/local/bin/tc-deploy-release.sh, mode 0755, permitted to the
# service user by exactly one sudoers rule.
#
# ---------------------------------------------------------------------------------------------
# THE RULE THIS FILE EXISTS TO ENFORCE (PR #79 review):
#
#   Root executes ONLY root-owned code that the service user cannot write.
#
# An earlier version of this wrapper exec'd `deploy-console.sh` from the release worktree under
# /opt/tc_ai_growth/releases/<sha>/. That worktree is created by, and writable by, `tcgrowth`.
# Checking `git rev-parse HEAD == <sha>` does NOT close that hole: it proves which commit was
# checked out, not that the files still match it. `tcgrowth` can edit the script after checkout
# and leave HEAD untouched. Nor can git itself be the witness — the worktree's `.git` is equally
# writable, so any verification computed from it can be forged by the same account.
#
# Therefore the privileged machinery lives OUTSIDE the repository, root-owned:
#
#   /usr/local/lib/tc-deploy/deploy-console.sh   root:root 0755
#
# Consequence, stated rather than hidden: a change to the deployment machinery itself is NOT
# picked up by running a deployment. Updating /usr/local/lib/tc-deploy/ is a deliberate host
# action with its own review. That is the correct asymmetry — the thing that performs deployments
# must not be silently replaceable by a deployment.
#
# What this script never does: take a path, a service name, a branch, a flag beyond --rollback,
# or any second argument; source or execute anything under /opt/tc_ai_growth; interpolate its
# argument into a shell string; or discover executable code from systemd state.
# ---------------------------------------------------------------------------------------------

set -euo pipefail

# Root-owned machinery. Nothing below /opt/tc_ai_growth is ever executed by this script.
ROOT_LIB=/usr/local/lib/tc-deploy
DEPLOY_SCRIPT="$ROOT_LIB/deploy-console.sh"

RELEASES_DIR=/opt/tc_ai_growth/releases
APP_DIR=/opt/tc_ai_growth/app
VENV="$APP_DIR/orchestrator/.venv"
STORE_DB="$APP_DIR/orchestrator/data/tc_growth.db"
SERVICE_USER=tcgrowth

die() { printf 'tc-deploy-release: %s\n' "$1" >&2; exit 2; }

# The privileged machinery must be root-owned and not group/other writable. Checked at every
# invocation, not assumed from install time: if someone loosened it since, this is where we stop.
assert_root_owned() {
    local path="$1"
    [ -f "$path" ] || die "missing root-owned machinery: $path (see WP-U4D-ENABLEMENT-GATE.md)"
    local meta
    meta="$(stat -c '%U %a' "$path")"
    case "$meta" in
        "root 755" | "root 750" | "root 700" | "root 555") ;;
        *) die "$path must be root-owned and not writable by others (found: $meta)" ;;
    esac
}

[ "$#" -eq 1 ] || die "expected exactly one argument (a 40-character commit SHA), got $#"
assert_root_owned "$DEPLOY_SCRIPT"

if [ "$1" = "--rollback" ]; then
    # Rollback takes no target: there is nothing to choose, so nothing to get wrong. It does NOT
    # discover a script through systemd's WorkingDirectory — that path points into a
    # service-user-writable worktree, so using it to select executable code would reintroduce the
    # very defect this file exists to prevent. Root-owned code, root-controlled snapshot state.
    exec "$DEPLOY_SCRIPT" --rollback
fi

SHA="$1"
case "$SHA" in
    *[!0-9a-f]* | "") die "not a lowercase 40-hex commit SHA" ;;
esac
[ "${#SHA}" -eq 40 ] || die "not a lowercase 40-hex commit SHA (length ${#SHA})"

REL="$RELEASES_DIR/$SHA"
[ -d "$REL" ] || die "no release worktree at $REL — the runner creates it before calling this"

# HEAD is still checked, but ONLY as a cheap sanity check that the caller staged the worktree it
# claims to have staged. It is explicitly NOT treated as a content-integrity or clean-worktree
# guarantee (see the header). The integrity control is that root runs $DEPLOY_SCRIPT, not
# anything from $REL.
HEAD="$(git -C "$REL" rev-parse HEAD 2>/dev/null || true)"
[ "$HEAD" = "$SHA" ] || die "release worktree HEAD ($HEAD) is not the requested SHA"

# The release worktree is DATA to the privileged step: the deploy script reads it to publish the
# unit's WorkingDirectory, and the Console later runs that code UNPRIVILEGED as $SERVICE_USER —
# which is the normal, accepted arrangement. What must never happen is root executing it.
export TC_RELEASE_DIR="$REL"
export TC_RELEASE_SHA="$SHA"
export TC_VENV="$VENV"
export TC_STORE_DB="$STORE_DB"
export TC_SERVICE_USER="$SERVICE_USER"
exec "$DEPLOY_SCRIPT" --apply
