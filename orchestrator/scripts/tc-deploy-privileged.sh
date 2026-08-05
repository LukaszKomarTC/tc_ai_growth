#!/bin/bash
# WP-U4d.1 increment 2 — the ONE privileged program (PR #80).
#
# This file is the reviewed SOURCE. It is never executed from the repository: `install-tc-deploy.sh`
# copies it into a root-owned prefix outside every service-user-writable tree, bakes that target's
# constants beside it, and records a digest manifest. Root executes only the installed copy.
#
# Why the whole thing is shaped this way — six defects from PR #79, each answered here:
#
# 1. ONE escalation, one entry point. The runner used to escalate twice (`sudo install`, then
#    `sudo deploy-console.sh`), and the second one handed root a script out of a tree the service
#    user owns. There is now a single sudoers rule, for this program, and it takes VERBS.
#
# 2. Root executes nothing from the checkout. Not the deploy script, not Python, not the inspector.
#    Everything root runs lives in the prefix and was put there at install time by the owner.
#
# 3. The trust anchor is written, not referenced. `$PREFIX/manifest.sha256` is a real root-owned
#    file created by a real installer, and this program refuses to do anything if it is missing,
#    unowned, writable by anyone else, or disagrees with the bytes on disk.
#
# 4. The permission predicate is the merged, proven one. `permission-guard.sh` is sourced from the
#    prefix after being verified. The bootstrap check below duplicates its numeric mask ON PURPOSE
#    (you cannot source a file to decide whether sourcing it is safe); a test pins that the two
#    agree on every mode.
#
# 5. The boundary does not end one process early. The inspector is installed from ROOT'S OWN COPY,
#    and the release's copy is compared against the root-owned manifest and REFUSED if it differs.
#    Copying release bytes into a root-executed location is what laundered the trust before.
#
# 6. Nothing here claims a phase it did not run. When systemd is not booted, the systemd phases
#    report `unavailable` and the program exits 3 — a distinct code meaning "the file-level work
#    completed, the manager-level work did not run". It never prints ok for something it skipped.
#
# Verbs (the complete interface — anything else is refused):
#   self-check          verify the installed machinery and print what it verified
#   apply <40-hex-sha>  deploy that release; file phases always, systemd phases when booted
#   rollback            restore the previous unit, inspector and sudoers from root-owned state
#   start-run <id>      create the transient per-deployment unit (systemd only)
#
# No path, user, service, unit or port is ever accepted from the caller. They are read from
# `$PREFIX/target.conf`, which is root-owned and verified before it is read.

set -uo pipefail

# A constructed environment, immediately. Whatever the caller exported is irrelevant from here on:
# nothing below reads an environment variable for a decision, and children inherit only this.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
unset IFS CDPATH BASH_ENV ENV GLOBIGNORE LD_PRELOAD LD_LIBRARY_PATH PYTHONPATH PYTHONHOME
umask 022

readonly EXIT_REFUSED=2          # policy said no
readonly EXIT_SYSTEMD_ABSENT=3   # file phases done, manager phases not run

die() { printf 'REFUSED: %s\n' "$*" >&2; exit "$EXIT_REFUSED"; }
phase() { printf 'phase=%-22s status=%s\n' "$1" "$2"; }
note() { printf '  %s\n' "$*"; }

# --------------------------------------------------------------------------- bootstrap
#
# Resolve our own installed location WITHOUT trusting $0's directory blindly, and without any
# environment variable. `readlink -f` gives the real path; PREFIX is its directory.

SELF="$(readlink -f "$0" 2>/dev/null)" || die "cannot resolve my own path"
[ -n "$SELF" ] || die "cannot resolve my own path"
PREFIX="$(dirname "$SELF")"
readonly SELF PREFIX

MANIFEST="$PREFIX/manifest.sha256"
GUARD="$PREFIX/permission-guard.sh"
TARGET_CONF="$PREFIX/target.conf"
readonly MANIFEST GUARD TARGET_CONF

[ "$(id -u)" -eq 0 ] || die "this program only runs as root; it is the privileged half by design"

# The bootstrap predicate. Deliberately identical in effect to mode_has_write_bits() in
# permission-guard.sh — see note 4 in the header. Returns 0 (true) when the mode is UNSAFE.
_bootstrap_mode_is_unsafe() {
    local mode="$1"
    [ -n "$mode" ] || return 0
    case "$mode" in *[!0-7]*) return 0 ;; esac
    (( 8#$mode & 8#22 ))
}

_owner_of() { stat -c %U:%G "$1" 2>/dev/null; }
_mode_of() { stat -c %a "$1" 2>/dev/null; }
_digest_of() { sha256sum "$1" 2>/dev/null | cut -d' ' -f1; }

# Every path root trusts must be root-owned and unwritable by anyone else, and so must every
# directory above it inside the prefix — a writable parent means the file can be swapped.
_assert_root_owned_and_locked() {
    local path="$1" owner mode
    [ -e "$path" ] || die "missing from the installed prefix: $path"
    owner="$(_owner_of "$path")"
    [ "$owner" = "root:root" ] || die "not root-owned: $path (owned by ${owner:-unknown})"
    mode="$(_mode_of "$path")"
    if _bootstrap_mode_is_unsafe "$mode"; then
        die "group- or other-writable, so its contents cannot be trusted: $path (mode ${mode:-unreadable})"
    fi
}

verify_machinery() {
    # The prefix itself first: a writable directory makes every check below meaningless.
    _assert_root_owned_and_locked "$PREFIX"
    _assert_root_owned_and_locked "$MANIFEST"

    # Then every file the manifest names, including this program. `sha256sum -c` is not used: it
    # would report a missing file as a failure line on stdout and still let a caller misread the
    # exit status, and it does not check ownership at all.
    local recorded="" name expected actual
    while read -r expected name; do
        [ -n "$expected" ] || continue
        case "$name" in
            ""|*/*|*..*) die "manifest names an unusable entry: '$name'" ;;
        esac
        _assert_root_owned_and_locked "$PREFIX/$name"
        actual="$(_digest_of "$PREFIX/$name")"
        [ -n "$actual" ] || die "cannot hash $PREFIX/$name"
        [ "$actual" = "$expected" ] || die "the installed $name does not match the root-owned manifest — refusing to run altered machinery"
        recorded="$recorded $name"
    done < "$MANIFEST"

    # The manifest must actually cover the things that matter, or an attacker could simply drop
    # entries rather than change bytes.
    local required
    for required in "$(basename "$SELF")" permission-guard.sh target.conf wp-integrity-scan.sh; do
        case " $recorded " in
            *" $required "*) ;;
            *) die "the manifest does not cover $required — an incomplete manifest is not a manifest" ;;
        esac
    done
    VERIFIED_FILES="$recorded"
}

VERIFIED_FILES=""
verify_machinery

# Only now is it safe to source the guard, and only now is target.conf trustworthy.
# shellcheck source=/dev/null
. "$GUARD" || die "could not load the permission guard"
command -v mode_has_write_bits >/dev/null || die "the permission guard did not define its predicate"
# Re-check the prefix with the MERGED predicate, so the proven implementation gets the last word.
mode_has_write_bits "$(_mode_of "$PREFIX")" && die "prefix is writable by others: $PREFIX"

# target.conf is `key=value` only — parsed, never sourced, so a planted line cannot execute.
TC_APP_DIR=""; TC_RELEASES_DIR=""; TC_SERVICE=""; TC_SERVICE_USER=""; TC_CONSOLE_PORT=""
TC_UNIT_PATH=""; TC_INSPECTOR_DEST=""; TC_SUDOERS_FILE=""; TC_SNAPSHOT_DIR=""; TC_UNIT_PREFIX=""
TC_STORE_DB=""; TC_VENV=""; TC_CONSOLE_ENV_FILE=""
while IFS='=' read -r key value; do
    case "$key" in
        ''|'#'*) continue ;;
        TC_APP_DIR|TC_RELEASES_DIR|TC_SERVICE|TC_SERVICE_USER|TC_CONSOLE_PORT|TC_UNIT_PATH|\
        TC_INSPECTOR_DEST|TC_SUDOERS_FILE|TC_SNAPSHOT_DIR|TC_UNIT_PREFIX|TC_STORE_DB|TC_VENV|\
        TC_CONSOLE_ENV_FILE)
            printf -v "$key" '%s' "$value" ;;
        *) die "target.conf contains an unknown key: $key" ;;
    esac
done < "$TARGET_CONF"

for required_key in TC_APP_DIR TC_RELEASES_DIR TC_SERVICE TC_SERVICE_USER TC_CONSOLE_PORT \
                    TC_UNIT_PATH TC_INSPECTOR_DEST TC_SUDOERS_FILE TC_SNAPSHOT_DIR TC_UNIT_PREFIX; do
    [ -n "${!required_key}" ] || die "target.conf is missing $required_key"
done

# The prefix must not live inside the tree the service user can write, or none of this holds.
case "$PREFIX/" in
    "$TC_APP_DIR"/*|"$TC_RELEASES_DIR"/*)
        die "the privileged prefix sits inside a service-user-writable tree: $PREFIX" ;;
esac

# --------------------------------------------------------------------------- helpers

# Run a child with a CONSTRUCTED environment. `env -i` rather than inheritance: the deployment
# runs as a child of the Console, and the Console's environment is not root's to trust.
run_clean() {
    env -i PATH="$PATH" HOME=/root LANG=C.UTF-8 "$@"
}

valid_sha() {
    case "$1" in
        *[!0-9a-f]*) return 1 ;;
        ????????????????????????????????????????) return 0 ;;
        *) return 1 ;;
    esac
}

# --------------------------------------------------------------------------- verbs

verb_self_check() {
    phase "verify-machinery" ok
    note "prefix ................ $PREFIX (root:root, mode $(_mode_of "$PREFIX"))"
    note "manifest ............. $MANIFEST"
    for name in $VERIFIED_FILES; do
        note "verified ............. $name  $(_digest_of "$PREFIX/$name" | cut -c1-12)"
    done
    phase "target-constants" ok
    note "app dir .............. $TC_APP_DIR"
    note "releases dir ......... $TC_RELEASES_DIR"
    note "service .............. $TC_SERVICE (user $TC_SERVICE_USER, port $TC_CONSOLE_PORT)"
    note "unit ................. $TC_UNIT_PATH"
    note "inspector dest ....... $TC_INSPECTOR_DEST"
    note "sudoers .............. $TC_SUDOERS_FILE"
    note "snapshots ............ $TC_SNAPSHOT_DIR"
    if [ -d /run/systemd/system ]; then
        phase "systemd" available
    else
        phase "systemd" unavailable
        note "PID 1 is not systemd; apply will complete its file phases and stop before the"
        note "manager phases rather than reporting a restart it did not perform."
        return "$EXIT_SYSTEMD_ABSENT"
    fi
    return 0
}

# The post-stage substitution defence. The unprivileged `stage` step already compared the release
# against the committed objects — but root does not take the unprivileged half's word for it, and
# the release tree stays writable after that check returns. Root compares the release's inspector
# against ITS OWN manifest digest, and installs from its own copy either way.
assert_release_inspector_matches_root() {
    local release="$1" release_inspector expected actual
    release_inspector="$release/orchestrator/scripts/wp-integrity-scan.sh"
    [ -f "$release_inspector" ] || die "the release has no inspector at orchestrator/scripts/wp-integrity-scan.sh"
    expected="$(_digest_of "$PREFIX/wp-integrity-scan.sh")"
    actual="$(_digest_of "$release_inspector")"
    [ -n "$actual" ] || die "cannot hash the release inspector"
    if [ "$actual" != "$expected" ]; then
        die "the release's inspector does not match the root-owned copy — the release content changed after review; refusing to deploy it"
    fi
}

verb_apply() {
    local sha="$1" release snapshot
    valid_sha "$sha" || die "apply takes an exact 40-character lowercase hex SHA and nothing else"

    # Re-derived from constants. The caller supplied a SHA and NOTHING else; the path is ours.
    release="$TC_RELEASES_DIR/$sha"
    [ -d "$release" ] || die "no release directory for $sha under the configured releases root"

    phase "verify-machinery" ok
    assert_release_inspector_matches_root "$release"
    phase "release-content" ok
    note "the release inspector matches the root-owned copy"

    # Snapshot into root-owned state, named by us. Rollback later selects the snapshot through
    # a root-written pointer, never through anything a caller can influence.
    snapshot="$TC_SNAPSHOT_DIR/$sha"
    run_clean install -d -m 0755 -o root -g root "$TC_SNAPSHOT_DIR" || die "cannot create $TC_SNAPSHOT_DIR"
    run_clean install -d -m 0755 -o root -g root "$snapshot" || die "cannot create $snapshot"
    [ -f "$TC_UNIT_PATH" ] && run_clean cp -a "$TC_UNIT_PATH" "$snapshot/unit.prev"
    [ -f "$TC_INSPECTOR_DEST" ] && run_clean cp -a "$TC_INSPECTOR_DEST" "$snapshot/inspector.prev"
    [ -f "$TC_SUDOERS_FILE" ] && run_clean cp -a "$TC_SUDOERS_FILE" "$snapshot/sudoers.prev"
    printf '%s\n' "$sha" > "$TC_SNAPSHOT_DIR/previous"
    run_clean chmod 0644 "$TC_SNAPSHOT_DIR/previous"
    phase "snapshot" ok
    note "root-owned snapshot at $snapshot"

    # From ROOT'S copy. Never from the release — that is the laundering this exists to stop.
    run_clean install -m 0755 -o root -g root "$PREFIX/wp-integrity-scan.sh" "$TC_INSPECTOR_DEST" \
        || die "could not install the inspector"
    phase "install-inspector" ok
    note "$TC_INSPECTOR_DEST installed from $PREFIX/wp-integrity-scan.sh"

    write_sudoers "$snapshot" || return "$EXIT_REFUSED"
    phase "install-sudoers" ok

    write_unit "$release" || return "$EXIT_REFUSED"
    phase "write-unit" ok
    note "$TC_UNIT_PATH pins $sha"

    if [ ! -d /run/systemd/system ]; then
        phase "daemon-reload" unavailable
        phase "restart-service" unavailable
        phase "health-check" unavailable
        note "systemd is not booted here; these phases did NOT run and nothing above should be"
        note "read as evidence that the service started. Run this verb on the target host."
        return "$EXIT_SYSTEMD_ABSENT"
    fi

    run_clean systemctl daemon-reload || die "daemon-reload failed"
    phase "daemon-reload" ok
    run_clean systemctl restart "$TC_SERVICE" || die "could not restart $TC_SERVICE"
    phase "restart-service" ok
    if run_clean curl -fsS -m 15 -o /dev/null "http://127.0.0.1:$TC_CONSOLE_PORT/"; then
        phase "health-check" ok
    else
        phase "health-check" failed
        die "$TC_SERVICE did not answer on 127.0.0.1:$TC_CONSOLE_PORT"
    fi
    return 0
}

write_sudoers() {
    local snapshot="$1" staged="$1/sudoers.next"
    # The rule grants the service user exactly this program with exactly these verbs, and the
    # inspector with zero arguments. It never grants a command PATH.
    cat > "$staged" <<SUDOERS
# Managed by tc-deploy. Do not edit by hand.
$TC_SERVICE_USER ALL=(root) NOPASSWD: $SELF apply [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]
$TC_SERVICE_USER ALL=(root) NOPASSWD: $SELF rollback
$TC_SERVICE_USER ALL=(root) NOPASSWD: $SELF self-check
$TC_SERVICE_USER ALL=(root) NOPASSWD: $TC_INSPECTOR_DEST ""
SUDOERS
    chmod 0440 "$staged"
    if command -v visudo >/dev/null; then
        run_clean visudo -c -f "$staged" >/dev/null || die "the generated sudoers drop-in does not validate"
    else
        note "visudo is not installed; the drop-in was NOT syntax-validated"
    fi
    run_clean install -m 0440 -o root -g root "$staged" "$TC_SUDOERS_FILE" \
        || die "could not install the sudoers drop-in"
}

write_unit() {
    local release="$1" staged="$TC_SNAPSHOT_DIR/unit.next"
    cat > "$staged" <<UNIT
[Unit]
Description=TC Operations Console ($TC_SERVICE)
After=network.target

[Service]
User=$TC_SERVICE_USER
WorkingDirectory=$release/orchestrator
Environment=TC_CONSOLE_PORT=$TC_CONSOLE_PORT
Environment=TC_BUILD_COMMIT=$(basename "$release")
${TC_STORE_DB:+Environment=TC_DB_PATH=$TC_STORE_DB}
${TC_CONSOLE_ENV_FILE:+EnvironmentFile=-$TC_CONSOLE_ENV_FILE}
ExecStart=${TC_VENV:-$release/orchestrator/.venv}/bin/python -m tc_growth.cli console $TC_CONSOLE_PORT
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
    run_clean install -m 0644 -o root -g root "$staged" "$TC_UNIT_PATH" \
        || die "could not install the unit file"
}

verb_rollback() {
    local previous snapshot
    [ -f "$TC_SNAPSHOT_DIR/previous" ] || die "no root-owned rollback pointer exists"
    _assert_root_owned_and_locked "$TC_SNAPSHOT_DIR/previous"
    previous="$(cat "$TC_SNAPSHOT_DIR/previous")"
    # Validated even though root wrote it: a pointer is still a value, and this is the class of
    # input that produced the WorkingDirectory defect in round 4.
    valid_sha "$previous" || die "the rollback pointer is not a SHA: refusing to act on it"
    snapshot="$TC_SNAPSHOT_DIR/$previous"
    _assert_root_owned_and_locked "$snapshot"
    phase "verify-machinery" ok
    phase "select-snapshot" ok
    note "restoring from $snapshot (selected by root-written pointer, not by the caller)"

    [ -f "$snapshot/unit.prev" ] && run_clean install -m 0644 -o root -g root "$snapshot/unit.prev" "$TC_UNIT_PATH"
    [ -f "$snapshot/inspector.prev" ] && run_clean install -m 0755 -o root -g root "$snapshot/inspector.prev" "$TC_INSPECTOR_DEST"
    [ -f "$snapshot/sudoers.prev" ] && run_clean install -m 0440 -o root -g root "$snapshot/sudoers.prev" "$TC_SUDOERS_FILE"
    phase "restore-files" ok

    if [ ! -d /run/systemd/system ]; then
        phase "daemon-reload" unavailable
        phase "restart-service" unavailable
        note "systemd is not booted here; the restored files are in place but the service was NOT"
        note "restarted and nothing above proves the previous release is serving."
        return "$EXIT_SYSTEMD_ABSENT"
    fi
    run_clean systemctl daemon-reload || die "daemon-reload failed"
    run_clean systemctl restart "$TC_SERVICE" || die "could not restart $TC_SERVICE"
    phase "restart-service" ok
    return 0
}

verb_start_run() {
    local run_id="$1"
    case "$run_id" in ''|*[!0-9]*) die "start-run takes a numeric run id and nothing else" ;; esac
    [ -d /run/systemd/system ] || {
        phase "transient-unit" unavailable
        note "systemd is not booted here; no transient unit was created."
        return "$EXIT_SYSTEMD_ABSENT"
    }
    # The transient unit is created through THIS program — issue #77 Decision 2 required that the
    # unit not become a second general capability, so `systemd-run` is never in the sudoers rule.
    run_clean systemd-run --collect --unit="$TC_UNIT_PREFIX-run-$run_id" \
        --uid="$TC_SERVICE_USER" --working-directory="$TC_APP_DIR/orchestrator" \
        "${TC_VENV:-$TC_APP_DIR/orchestrator/.venv}/bin/python" -m tc_growth.cli deploy-run "$run_id" \
        || die "could not create the transient deployment unit"
    phase "transient-unit" ok
    note "$TC_UNIT_PREFIX-run-$run_id created"
    return 0
}

# --------------------------------------------------------------------------- dispatch
#
# A closed table. There is no default branch that runs "whatever was asked for", no option
# parsing, and no way to reach a shell.

case "${1-}" in
    self-check) [ $# -eq 1 ] || die "self-check takes no arguments"; verb_self_check ;;
    apply)      [ $# -eq 2 ] || die "apply takes exactly one argument, the target SHA"; verb_apply "$2" ;;
    rollback)   [ $# -eq 1 ] || die "rollback takes no arguments"; verb_rollback ;;
    start-run)  [ $# -eq 2 ] || die "start-run takes exactly one argument, the run id"; verb_start_run "$2" ;;
    *)          die "not a verb: '${1-}' (the interface is: self-check, apply <sha>, rollback, start-run <id>)" ;;
esac
