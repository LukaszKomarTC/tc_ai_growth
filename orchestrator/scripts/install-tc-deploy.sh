#!/bin/bash
# WP-U4d.1 increment 2 — the installer that WRITES the trust anchor (PR #80).
#
# PR #79 defect 3 was a trust anchor that appeared in the code, the docs and the PR description
# and existed in none of them. This is the program that creates it, it is executed by the
# disposable harness on every run, and its output is attached to the PR.
#
# What it does, once, as an owner-performed act:
#
#   * copies the reviewed privileged program, the merged permission guard and the reviewed
#     inspector into a root-owned prefix OUTSIDE every service-user-writable tree;
#   * bakes that target's constants into `target.conf` beside them, so the privileged program
#     never takes a path, user, service, unit or port from a caller;
#   * records a `manifest.sha256` covering all four, root-owned;
#   * then runs the INSTALLED program's `self-check` and fails the install if it does not verify.
#
# The last step matters more than it looks. An installer that reports success without exercising
# what it installed is exactly how a path that dies on first use passes review four times.
#
# Copying FROM the checkout is deliberate and is not the laundering defect. Installation is a
# reviewed act the owner performs at a known moment; deployment is an automated act performed by
# an unprivileged service. The defect was root reading service-user-writable bytes at DEPLOY time,
# which is precisely what the installed copy plus manifest now prevents.

set -uo pipefail

die() { printf 'install-tc-deploy: %s\n' "$*" >&2; exit 2; }
say() { printf '%s\n' "$*"; }

PREFIX=""; APP_DIR=""; RELEASES_DIR=""; SERVICE=""; SERVICE_USER=""; PORT=""
UNIT_PATH=""; INSPECTOR_DEST=""; SUDOERS_FILE=""; SNAPSHOT_DIR=""; UNIT_PREFIX=""
STORE_DB=""; VENV=""; CONSOLE_ENV_FILE=""; SOURCE_DIR=""

usage() {
    cat <<'USAGE'
Usage: install-tc-deploy.sh --prefix DIR --app-dir DIR --releases-dir DIR \
         --service NAME --service-user NAME --port N --unit-path FILE \
         --inspector-dest FILE --sudoers-file FILE --snapshot-dir DIR --unit-prefix NAME \
         [--store-db FILE] [--venv DIR] [--console-env-file FILE] [--source DIR]

Installs the single privileged deployment entry point for ONE target. Run as root.
--source defaults to the directory containing this script (the reviewed checkout).
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="${2-}"; shift 2 ;;
        --app-dir) APP_DIR="${2-}"; shift 2 ;;
        --releases-dir) RELEASES_DIR="${2-}"; shift 2 ;;
        --service) SERVICE="${2-}"; shift 2 ;;
        --service-user) SERVICE_USER="${2-}"; shift 2 ;;
        --port) PORT="${2-}"; shift 2 ;;
        --unit-path) UNIT_PATH="${2-}"; shift 2 ;;
        --inspector-dest) INSPECTOR_DEST="${2-}"; shift 2 ;;
        --sudoers-file) SUDOERS_FILE="${2-}"; shift 2 ;;
        --snapshot-dir) SNAPSHOT_DIR="${2-}"; shift 2 ;;
        --unit-prefix) UNIT_PREFIX="${2-}"; shift 2 ;;
        --store-db) STORE_DB="${2-}"; shift 2 ;;
        --venv) VENV="${2-}"; shift 2 ;;
        --console-env-file) CONSOLE_ENV_FILE="${2-}"; shift 2 ;;
        --source) SOURCE_DIR="${2-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown argument: $1" ;;
    esac
done

[ "$(id -u)" -eq 0 ] || die "run as root: this installs root-owned machinery"

for required in PREFIX APP_DIR RELEASES_DIR SERVICE SERVICE_USER PORT UNIT_PATH \
                INSPECTOR_DEST SUDOERS_FILE SNAPSHOT_DIR UNIT_PREFIX; do
    [ -n "${!required}" ] || { usage >&2; die "missing --${required,,}" ; }
done

SOURCE_DIR="${SOURCE_DIR:-$(cd "$(dirname "$0")" && pwd)}"
[ -f "$SOURCE_DIR/tc-deploy-privileged.sh" ] || die "no tc-deploy-privileged.sh under $SOURCE_DIR"
[ -f "$SOURCE_DIR/lib/permission-guard.sh" ] || die "no lib/permission-guard.sh under $SOURCE_DIR"
[ -f "$SOURCE_DIR/wp-integrity-scan.sh" ] || die "no wp-integrity-scan.sh under $SOURCE_DIR"

# Absolute, normalised paths only. A relative or `..`-bearing prefix would make every later
# ownership claim depend on the caller's working directory.
for path_var in PREFIX APP_DIR RELEASES_DIR UNIT_PATH INSPECTOR_DEST SUDOERS_FILE SNAPSHOT_DIR; do
    value="${!path_var}"
    case "$value" in
        /*) ;;
        *) die "--${path_var,,} must be absolute: $value" ;;
    esac
    case "$value" in
        *..*|*//*) die "--${path_var,,} must be normalised (no .. or //): $value" ;;
    esac
done

case "$PORT" in ''|*[!0-9]*) die "--port must be numeric: $PORT" ;; esac
case "$SERVICE" in *[!a-zA-Z0-9._-]*) die "--service must be a plain unit-safe name: $SERVICE" ;; esac
case "$UNIT_PREFIX" in *[!a-zA-Z0-9._-]*) die "--unit-prefix must be a plain name: $UNIT_PREFIX" ;; esac

# The property the whole increment rests on: root's machinery must not live where the service
# user can reach it. Checked here rather than trusted, because getting it wrong silently would
# make every downstream digest check theatre.
case "$PREFIX/" in
    "$APP_DIR"/*|"$RELEASES_DIR"/*)
        die "--prefix is inside a service-user-writable tree ($PREFIX); install it elsewhere" ;;
esac

say "installing the privileged deployment entry point"
say "  prefix ......... $PREFIX"
say "  source ......... $SOURCE_DIR"

install -d -m 0755 -o root -g root "$PREFIX" || die "cannot create $PREFIX"
install -m 0755 -o root -g root "$SOURCE_DIR/tc-deploy-privileged.sh" "$PREFIX/tc-deploy-privileged.sh" \
    || die "cannot install the privileged program"
install -m 0644 -o root -g root "$SOURCE_DIR/lib/permission-guard.sh" "$PREFIX/permission-guard.sh" \
    || die "cannot install the permission guard"
# 0644, not 0755: root installs the inspector to its executable destination at apply time from
# THIS copy. Nothing executes it from the prefix, so it needs no execute bit here.
install -m 0644 -o root -g root "$SOURCE_DIR/wp-integrity-scan.sh" "$PREFIX/wp-integrity-scan.sh" \
    || die "cannot install the inspector bytes"

umask 022
cat > "$PREFIX/target.conf" <<CONF
# Managed by install-tc-deploy.sh. The privileged program PARSES this file; it never sources it.
TC_APP_DIR=$APP_DIR
TC_RELEASES_DIR=$RELEASES_DIR
TC_SERVICE=$SERVICE
TC_SERVICE_USER=$SERVICE_USER
TC_CONSOLE_PORT=$PORT
TC_UNIT_PATH=$UNIT_PATH
TC_INSPECTOR_DEST=$INSPECTOR_DEST
TC_SUDOERS_FILE=$SUDOERS_FILE
TC_SNAPSHOT_DIR=$SNAPSHOT_DIR
TC_UNIT_PREFIX=$UNIT_PREFIX
TC_STORE_DB=$STORE_DB
TC_VENV=$VENV
TC_CONSOLE_ENV_FILE=$CONSOLE_ENV_FILE
CONF
chown root:root "$PREFIX/target.conf" && chmod 0644 "$PREFIX/target.conf" \
    || die "cannot secure target.conf"

# The manifest, written last and covering everything above. Basenames only: the privileged
# program resolves them against its own prefix, so a manifest entry can never point elsewhere.
( cd "$PREFIX" && sha256sum tc-deploy-privileged.sh permission-guard.sh wp-integrity-scan.sh \
    target.conf > manifest.sha256 ) || die "cannot write the manifest"
chown root:root "$PREFIX/manifest.sha256" && chmod 0644 "$PREFIX/manifest.sha256" \
    || die "cannot secure the manifest"

say ""
say "verifying the INSTALLED program by running it — an installer that does not exercise what it"
say "installed is how a path that dies on first use passes review:"
say ""
"$PREFIX/tc-deploy-privileged.sh" self-check
rc=$?
say ""
case "$rc" in
    0) say "install complete; systemd is booted and the target is fully addressable." ;;
    3) say "install complete. systemd is NOT booted here, so self-check reported the manager"
       say "phases as unavailable. That is the expected result off-host and is not a failure." ;;
    *) die "the installed program failed its own self-check (exit $rc) — install rejected" ;;
esac
exit 0
