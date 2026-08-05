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
STORE_DB=""; VENV=""; CONSOLE_ENV_FILE=""; SOURCE_DIR=""; RUNTIME_DIR=""
PROVISION_VENV=0; PYTHON_FOR_VENV=""; VENV_SYSTEM_SITE=0

usage() {
    cat <<'USAGE'
Usage: install-tc-deploy.sh --prefix DIR --app-dir DIR --releases-dir DIR \
         --service NAME --service-user NAME --port N --unit-path FILE \
         --inspector-dest FILE --sudoers-file FILE --snapshot-dir DIR --unit-prefix NAME \
         --runtime-dir DIR \
         [--store-db FILE] [--venv DIR] [--console-env-file FILE] [--source DIR]
         [--provision-venv] [--python PYTHON] [--venv-system-site-packages]

--provision-venv creates a ROOT-OWNED virtualenv at --venv. Without it, --venv is validated and
the install is rejected if the service user could write the interpreter.

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
        --runtime-dir) RUNTIME_DIR="${2-}"; shift 2 ;;
        --store-db) STORE_DB="${2-}"; shift 2 ;;
        --venv) VENV="${2-}"; shift 2 ;;
        --console-env-file) CONSOLE_ENV_FILE="${2-}"; shift 2 ;;
        --source) SOURCE_DIR="${2-}"; shift 2 ;;
        --provision-venv) PROVISION_VENV=1; shift ;;
        --venv-system-site-packages) VENV_SYSTEM_SITE=1; shift ;;
        --python) PYTHON_FOR_VENV="${2-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown argument: $1" ;;
    esac
done

[ "$(id -u)" -eq 0 ] || die "run as root: this installs root-owned machinery"

for required in PREFIX APP_DIR RELEASES_DIR SERVICE SERVICE_USER PORT UNIT_PATH \
                INSPECTOR_DEST SUDOERS_FILE SNAPSHOT_DIR UNIT_PREFIX RUNTIME_DIR; do
    [ -n "${!required}" ] || { usage >&2; die "missing --${required,,}" ; }
done

SOURCE_DIR="${SOURCE_DIR:-$(cd "$(dirname "$0")" && pwd)}"
[ -f "$SOURCE_DIR/tc-deploy-privileged.sh" ] || die "no tc-deploy-privileged.sh under $SOURCE_DIR"
[ -f "$SOURCE_DIR/lib/permission-guard.sh" ] || die "no lib/permission-guard.sh under $SOURCE_DIR"
[ -f "$SOURCE_DIR/wp-integrity-scan.sh" ] || die "no wp-integrity-scan.sh under $SOURCE_DIR"

# Absolute, normalised paths only. A relative or `..`-bearing prefix would make every later
# ownership claim depend on the caller's working directory.
for path_var in PREFIX APP_DIR RELEASES_DIR UNIT_PATH INSPECTOR_DEST SUDOERS_FILE SNAPSHOT_DIR RUNTIME_DIR; do
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
# The runtime tree is what the service actually executes, so it carries the same requirement.
case "$RUNTIME_DIR/" in
    "$APP_DIR"/*|"$RELEASES_DIR"/*)
        die "--runtime-dir is inside a service-user-writable tree ($RUNTIME_DIR); the whole point is that the service user cannot reach what runs" ;;
esac

# --------------------------------------------------------------- the interpreter, decided here
#
# Review blocker 3. `resolve_interpreter()` in the privileged program refuses an interpreter the
# service user can write — correctly, because a writable venv changes what executes without
# touching one application file. But production's venv IS service-user-owned today, so that
# refusal would have made the real apply path fail at the last step. Safe, and useless.
#
# So the decision is made at INSTALL time, once, by the owner, rather than discovered at deploy
# time by a refusal:
#
#   * `--provision-venv` creates a root-owned virtualenv at --venv and locks it down;
#   * otherwise --venv (or the runtime tree's own .venv) is CHECKED here and the install is
#     rejected with the exact remediation if it would not satisfy the boundary.
#
# The operational consequence, stated because it is real and permanent: a root-owned venv means
# dependency changes are a root-performed provisioning step, not something a deployment does.
# `pip install` during a deploy would put the service user back in control of what root's unit
# executes, which is the whole thing this increment exists to prevent.
#
# And it must hold only PINNED THIRD-PARTY dependencies. An editable install of the application
# writes a `.pth`/`__editable__*` finder that resolves imports back into the release tree, which
# would give a root-owned interpreter importing service-user-writable code — every ownership
# property satisfied and the application still mutable. The privileged program refuses such a
# venv at apply time; this refuses it at install time, where the owner is present to fix it.

# This MUST mirror resolve_interpreter() in tc-deploy-privileged.sh, or the installer will bless
# something the deployment then refuses — which is worse than no check at all, because it moves
# the failure to the one moment nobody is watching.
#
# In particular: a venv's bin/python is a SYMLINK, and symlink modes are always 0777 on Linux.
# Checking the link's mode rejects every virtualenv in existence while proving nothing. What
# matters is the directory (permission to replace the link comes from there), the resolved binary,
# and the link's owner.
_owner_is_root() { [ "$(stat -c %U:%G "$1" 2>/dev/null)" = "root:root" ]; }

_not_group_or_other_writable() {
    local mode
    mode="$(stat -c %a "$1" 2>/dev/null)"
    [ -n "$mode" ] || return 1
    case "$mode" in *[!0-7]*) return 1 ;; esac
    (( 8#$mode & 8#22 )) && return 1
    return 0
}

interpreter_is_locked() {
    local entry="$1" real
    [ -e "$entry" ] || return 1
    real="$(readlink -f "$entry")" || return 1
    _owner_is_root "$entry" || return 1
    _owner_is_root "$real" && _not_group_or_other_writable "$real" || return 1
    _owner_is_root "$(dirname "$entry")" && _not_group_or_other_writable "$(dirname "$entry")"
}

if [ "$PROVISION_VENV" = 1 ]; then
    [ -n "$VENV" ] || die "--provision-venv needs --venv to say where"
    say "provisioning a root-owned virtualenv at $VENV"
    if [ ! -x "$VENV/bin/python" ]; then
        venv_args=()
        # Dependencies have to come from somewhere root controls. Either root installs them into
        # this venv at provisioning time (the production shape), or the venv inherits the
        # system's — also root-owned — packages. What must never happen is a deployment running
        # `pip install` into the interpreter root's unit executes.
        [ "$VENV_SYSTEM_SITE" = 1 ] && venv_args+=(--system-site-packages)
        "${PYTHON_FOR_VENV:-python3}" -m venv "${venv_args[@]}" "$VENV" \
            || die "could not create a virtualenv at $VENV"
    fi
    chown -R root:root "$VENV" || die "could not take ownership of $VENV"
    # go-w, but readable and executable: the service user must be able to RUN the interpreter,
    # and must not be able to change it.
    chmod -R go-w "$VENV" || die "could not lock down $VENV"
    say "  $VENV is root-owned and not writable by the service user"
    say "  dependency installation is now a ROOT action, and must NOT be an editable install:"
    say "      sudo $VENV/bin/pip install --no-deps -r <reviewed-requirements.txt>"
    say "  \`pip install -e <release>/orchestrator\` would write a finder into this venv pointing"
    say "  back at the service-user-writable release tree — a root-owned interpreter importing"
    say "  mutable code. The application imports from the authenticated runtime working directory."
    say ""
fi

if [ -n "$VENV" ]; then
    if ! interpreter_is_locked "$VENV/bin/python"; then
        die "the interpreter at $VENV/bin/python does not satisfy the boundary the privileged
program enforces: both it and its directory must be root-owned and not group/other writable.
The deployment would be refused at its last step, so this install is rejected instead.

Fix it either way:
  re-run with --provision-venv         (creates and locks a root-owned venv at that path), or
  sudo chown -R root:root $VENV && sudo chmod -R go-w $VENV   (adopt the existing one)

Then install dependencies AS ROOT — a venv the service user can write is a venv the service user
can use to change what your unit executes."
    fi
    say "  interpreter ..... $VENV/bin/python (root-owned, not service-user writable)"
fi

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
TC_RUNTIME_DIR=$RUNTIME_DIR
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
