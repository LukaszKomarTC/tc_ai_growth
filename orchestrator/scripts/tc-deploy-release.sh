#!/bin/bash
# WP-U4d — the ONLY root-privileged action in the governed deployment runner.
#
# Installed root-owned at /usr/local/bin/tc-deploy-release.sh, mode 0755, and permitted to the
# service user by exactly one sudoers rule. Everything else the runner does happens unprivileged,
# because the runner already IS the service user.
#
# The design rule that matters: the argument is a 40-hex commit SHA and NOTHING else. It is
# validated here, by root-owned code, before it is used — not merely by the caller. A caller that
# can reach sudo can pass any string; this script is what decides that only a SHA is meaningful.
#
# What this script deliberately does NOT do:
#   - take a path, a service name, a branch, a flag, or any second argument;
#   - execute anything from a directory the service user can write, EXCEPT the release worktree's
#     own deploy script, which is a checkout of a reviewed commit that was verified to be an
#     ancestor of origin/main before this script was reached (see the runner's preflight step);
#   - source, eval, or interpolate the argument into a shell string.
#
# Rollback is a separate, equally narrow entry point: `--rollback` takes no SHA at all.

set -euo pipefail

RELEASES_DIR=/opt/tc_ai_growth/releases
APP_DIR=/opt/tc_ai_growth/app
VENV="$APP_DIR/orchestrator/.venv"
STORE_DB="$APP_DIR/orchestrator/data/tc_growth.db"

die() { printf 'tc-deploy-release: %s\n' "$1" >&2; exit 2; }

[ "$#" -eq 1 ] || die "expected exactly one argument (a 40-character commit SHA), got $#"

if [ "$1" = "--rollback" ]; then
    # Rollback restores the PREVIOUS snapshot and needs no target: there is nothing to choose,
    # so nothing to get wrong. It runs from the currently deployed release checkout.
    CURRENT="$(systemctl show tc-console --no-pager -p WorkingDirectory --value || true)"
    case "$CURRENT" in
        "$RELEASES_DIR"/*) ;;
        *) die "the running service does not point at a release worktree; refusing to roll back" ;;
    esac
    exec "$CURRENT/scripts/deploy-console.sh" --rollback
fi

SHA="$1"
case "$SHA" in
    *[!0-9a-f]* | "") die "not a lowercase 40-hex commit SHA" ;;
esac
[ "${#SHA}" -eq 40 ] || die "not a lowercase 40-hex commit SHA (length ${#SHA})"

REL="$RELEASES_DIR/$SHA"
[ -d "$REL" ] || die "no release worktree at $REL — the runner creates it before calling this"
[ -x "$REL/orchestrator/scripts/deploy-console.sh" ] || die "release checkout has no deploy script"

# The release worktree is a checkout of the reviewed SHA. The runner's preflight step already
# refused anything that is not an ancestor of origin/main; re-check the checkout's own HEAD here
# so this script does not depend on the caller having done so.
HEAD="$(git -C "$REL" rev-parse HEAD)"
[ "$HEAD" = "$SHA" ] || die "release worktree HEAD ($HEAD) is not the requested SHA"

cd "$REL/orchestrator"
export TC_VENV="$VENV"
export TC_STORE_DB="$STORE_DB"
exec ./scripts/deploy-console.sh --apply
