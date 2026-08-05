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
#   bootstrap <sha>     ONE-TIME setup: establish the trusted runner runtime so start-run has
#                       immutable code to launch from on a fresh host. Never in sudoers.
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
TC_STORE_DB=""; TC_VENV=""; TC_CONSOLE_ENV_FILE=""; TC_RUNTIME_DIR=""
while IFS='=' read -r key value; do
    case "$key" in
        ''|'#'*) continue ;;
        TC_APP_DIR|TC_RELEASES_DIR|TC_SERVICE|TC_SERVICE_USER|TC_CONSOLE_PORT|TC_UNIT_PATH|\
        TC_INSPECTOR_DEST|TC_SUDOERS_FILE|TC_SNAPSHOT_DIR|TC_UNIT_PREFIX|TC_STORE_DB|TC_VENV|\
        TC_CONSOLE_ENV_FILE|TC_RUNTIME_DIR)
            printf -v "$key" '%s' "$value" ;;
        *) die "target.conf contains an unknown key: $key" ;;
    esac
done < "$TARGET_CONF"

for required_key in TC_APP_DIR TC_RELEASES_DIR TC_SERVICE TC_SERVICE_USER TC_CONSOLE_PORT \
                    TC_UNIT_PATH TC_INSPECTOR_DEST TC_SUDOERS_FILE TC_SNAPSHOT_DIR \
                    TC_UNIT_PREFIX TC_RUNTIME_DIR; do
    [ -n "${!required_key}" ] || die "target.conf is missing $required_key"
done

# The prefix must not live inside the tree the service user can write, or none of this holds.
# The RUNTIME dir carries the same requirement for the same reason: it is what the service will
# actually execute, so a service-user-writable runtime would defeat the whole point of copying.
case "$PREFIX/" in
    "$TC_APP_DIR"/*|"$TC_RELEASES_DIR"/*)
        die "the privileged prefix sits inside a service-user-writable tree: $PREFIX" ;;
esac
case "$TC_RUNTIME_DIR/" in
    "$TC_APP_DIR"/*|"$TC_RELEASES_DIR"/*)
        die "the runtime directory sits inside a service-user-writable tree: $TC_RUNTIME_DIR" ;;
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

# --------------------------------------------------------------- pinning the COMPLETE runtime
#
# Review blocker 1. Authenticating the inspector and then writing a unit whose WorkingDirectory
# and ExecStart point into the release tree pins one artifact and leaves the application itself
# mutable: after `stage` returns ok, the service user can still edit `tc_growth/*.py`, templates,
# package metadata or the venv entry point, and the restarted service executes bytes nobody
# authorized. Root never imports that Python — but the deployment still *caused* unverified
# mutable content to become the running application, which is the same failure wearing a
# different hat.
#
# The fix is not another check. A check leaves a window; ownership does not. Root COPIES the
# release into a directory only root can write, records a full-tree manifest of its own copy,
# re-verifies immediately before the restart, and points the unit at the copy. From the moment
# of the copy there is no interval in which the service user can redirect what runs, because the
# bytes that run are not theirs to touch.
#
# What this does NOT establish, and it matters: root copies whatever the release tree held at
# copy time. Authenticity — "this tree really is commit <sha>" — still rests on the unprivileged
# `stage` step comparing against a git object store the service user can write. Closing THAT
# needs commit signatures verified against a root-held key, and it is the next anchor increment,
# not this one. What is closed here is the window between verification and consumption.

materialize_runtime() {
    # Separate statements, not one `local a=$1 b=$a`. Under `set -u` this bash does NOT make the
    # first name visible to the second assignment, so the b= form silently resolved to the
    # CALLER's variable through dynamic scoping — which happened to be right in apply and wrong
    # everywhere else. Found by start-run, whose caller names it `current`.
    local sha="$1" release="$2" runtime manifest
    runtime="$TC_RUNTIME_DIR/$sha"
    manifest="$TC_RUNTIME_DIR/$sha.manifest"

    run_clean install -d -m 0755 -o root -g root "$TC_RUNTIME_DIR" || die "cannot create $TC_RUNTIME_DIR"
    # A previous materialisation is root-owned, so removing it is safe and keeps apply idempotent.
    [ -e "$runtime" ] && run_clean rm -rf "$runtime"
    run_clean install -d -m 0755 -o root -g root "$runtime" || die "cannot create $runtime"
    run_clean cp -a "$release/." "$runtime/" || die "could not copy the release into root-owned storage"
    # `.git` in a worktree is a POINTER back into the service user's repository. It is not runtime
    # content and root has no business carrying it into a tree it vouches for.
    run_clean rm -rf "$runtime/.git"
    run_clean chown -R root:root "$runtime" || die "could not take ownership of the runtime copy"
    # Strip every group/other write bit. This is the property, not a tidy-up.
    run_clean chmod -R go-w "$runtime" || die "could not lock the runtime copy"

    ( cd "$runtime" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0r sha256sum ) \
        > "$manifest" || die "could not record the runtime manifest"
    run_clean chown root:root "$manifest" && run_clean chmod 0644 "$manifest" \
        || die "could not secure the runtime manifest"
}

# Ownership alone is not enough, and finding that out is what this function exists for.
#
# Copying the release into root-owned storage closes the window AFTER the copy — but the copy
# happens after `stage`, so a substitution in that gap is faithfully copied and then faithfully
# executed. "Root owns it" would then mean "root owns the attacker's bytes".
#
# So root authenticates the tree ITSELF, against the commit, using its own git invocation with
# the repository's configuration neutralised. Not the unprivileged step's verdict — root's own.
#
# Residual, stated plainly: the object database lives in the service user's checkout, so an
# adversary who can rewrite git objects *and* the tree consistently still passes. Closing that
# needs commit signatures verified against a root-held key, and it is the next anchor increment.
# What this closes is the post-`stage` substitution window, which is what was open.
# `--no-replace-objects` and GIT_NO_REPLACE_OBJECTS=1 are the load-bearing part, not tidiness.
#
# `refs/replace/<oid>` makes git substitute one object for another TRANSPARENTLY: `ls-tree` and
# `cat-file` then return the replacement while every command still names the authorized SHA. The
# service user owns this repository, so they can write that ref — and root's "I authenticated the
# tree against commit X myself" would be a statement about objects the adversary chose. Both the
# flag and the variable are set because the flag covers this invocation and the variable covers
# anything git re-execs.
#
# Grafts are deliberately not addressed here: they rewrite a commit's PARENTS, not its tree, and
# this reads trees. Alternates cannot help an attacker either — objects are looked up by exact
# oid, and an extra object source does not change which oid a tree entry names.
git_ro() {
    env -i PATH="$PATH" HOME=/root LANG=C.UTF-8 \
        GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null GIT_TERMINAL_PROMPT=0 \
        GIT_NO_REPLACE_OBJECTS=1 \
        git --no-replace-objects \
            -c core.fsmonitor= -c core.hooksPath=/dev/null -c core.pager=cat "$@"
}

verify_against_commit() {
    local sha="$1" runtime="$2" expected actual line mode kind oid path
    expected="$(mktemp)" || die "cannot stage the expected manifest"
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        mode="${line%% *}"; line="${line#* }"
        kind="${line%% *}"; line="${line#* }"
        oid="${line%%$'\t'*}"; path="${line#*$'\t'}"
        [ "$kind" = "blob" ] || { rm -f "$expected"; die "unsupported $kind entry in commit $sha: $path"; }
        printf '%s  ./%s\n' \
            "$(git_ro -C "$TC_APP_DIR" cat-file blob "$oid" | sha256sum | cut -d' ' -f1)" "$path" \
            >> "$expected"
    done < <(git_ro -C "$TC_APP_DIR" ls-tree -r "$sha" 2>/dev/null)

    [ -s "$expected" ] || { rm -f "$expected"; die "could not read the tree of commit $sha from the object store"; }
    actual="$(mktemp)"
    ( cd "$runtime" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0r sha256sum ) > "$actual"
    LC_ALL=C sort -o "$expected" "$expected"
    LC_ALL=C sort -o "$actual" "$actual"
    if ! cmp -s "$expected" "$actual"; then
        local diffs
        diffs="$(diff "$expected" "$actual" | grep -E '^[<>]' | head -5 | tr '\n' ';')"
        rm -f "$expected" "$actual"
        die "the runtime tree does not match commit $sha — content was substituted after the release was staged; refusing to run it ($diffs)"
    fi
    rm -f "$expected" "$actual"
}

verify_runtime() {
    local sha="$1" runtime manifest actual        # see materialize_runtime on why these split
    runtime="$TC_RUNTIME_DIR/$sha"
    manifest="$TC_RUNTIME_DIR/$sha.manifest"
    _assert_root_owned_and_locked "$TC_RUNTIME_DIR"
    _assert_root_owned_and_locked "$runtime"
    _assert_root_owned_and_locked "$manifest"
    actual="$(cd "$runtime" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0r sha256sum)"
    [ "$actual" = "$(cat "$manifest")" ] \
        || die "the root-owned runtime tree no longer matches its manifest — refusing to start it"
    # Nothing inside may be writable by anyone but root, or "immutable to the service user" is a
    # claim rather than a fact. One find, checked as a whole.
    local loose
    loose="$(find "$runtime" \( -perm -g+w -o -perm -o+w \) -print -quit)"
    [ -z "$loose" ] && return 0
    die "the runtime tree contains group/other-writable content ($loose)"
}

# Review blocker: a root-owned interpreter and a root-owned working directory are not enough if
# the venv itself points imports somewhere mutable.
#
# `pip install -e <release>/orchestrator` writes a `.pth` file or an `__editable__*` finder into
# site-packages that resolves `tc_growth` back to the release tree. The unit would then have a
# root-owned interpreter, a root-owned WorkingDirectory, and still import the service user's
# code — every property above satisfied and the actual application mutable. Which is why this
# checks where imports can COME FROM, not just what runs.
assert_no_import_path_into_mutable_trees() {
    local interpreter="$1" site offender
    for site in $("$interpreter" -c \
        'import site,sys,json
paths = set(sys.path)
try: paths.update(site.getsitepackages())
except Exception: pass
try: paths.add(site.getusersitepackages())
except Exception: pass
print("\n".join(p for p in paths if p))' 2>/dev/null); do
        [ -d "$site" ] || continue
        # Any redirection file that names a tree the service user can write.
        offender="$(grep -rlE "$TC_APP_DIR|$TC_RELEASES_DIR" "$site" \
            --include='*.pth' --include='__editable__*' 2>/dev/null | head -1)"
        [ -n "$offender" ] && die \
"the trusted virtualenv redirects imports into a service-user-writable tree: $offender

An editable install (pip install -e) points the root-owned venv back at the release checkout, so
the unit would run a root-owned interpreter from a root-owned directory and still import mutable
code. Install pinned third-party dependencies into the venv instead, and let the application
import from the authenticated root-owned runtime working directory."
    done
    return 0
}

# The interpreter is part of what the SHA has to cover: a venv the service user can write is a
# way to change what executes without touching a single application file.
resolve_interpreter() {
    local sha="$1" candidate real
    candidate="${TC_VENV:+$TC_VENV/bin/python}"
    [ -n "$candidate" ] || candidate="$TC_RUNTIME_DIR/$sha/orchestrator/.venv/bin/python"
    [ -e "$candidate" ] || die "no interpreter at $candidate"
    real="$(readlink -f "$candidate")" || die "cannot resolve the interpreter at $candidate"
    # Three checks, because each one alone has a hole:
    #   * the DIRECTORY holding the entry point — a writable directory means the entry can be
    #     replaced or re-pointed regardless of what it currently is;
    #   * the RESOLVED binary — otherwise a fine-looking symlink to a swapped interpreter passes;
    #   * the entry point's OWNER — but not its mode, because a symlink's mode is always 0777 on
    #     Linux and carries no meaning. Checking it would refuse every venv ever made while
    #     proving nothing; permission to replace a symlink comes from its directory.
    _assert_root_owned_and_locked "$(dirname "$candidate")"
    _assert_root_owned_and_locked "$real"
    assert_no_import_path_into_mutable_trees "$candidate"
    local owner
    owner="$(_owner_of "$candidate")"
    [ "$owner" = "root:root" ] || die "the interpreter entry point is not root-owned: $candidate (owned by ${owner:-unknown})"
    printf '%s\n' "$candidate"
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
    # Review blocker 2. Copying a file "if it exists" records CONTENT but silently loses ABSENCE,
    # and rollback then cannot tell "restore these bytes" from "there was nothing here". On a
    # first deployment that left the newly installed unit, inspector and sudoers drop-in in place
    # and called it restoration. The state file makes absence a recorded fact.
    : > "$snapshot/state"
    _snapshot_artifact unit "$TC_UNIT_PATH" "$snapshot"
    _snapshot_artifact inspector "$TC_INSPECTOR_DEST" "$snapshot"
    _snapshot_artifact sudoers "$TC_SUDOERS_FILE" "$snapshot"
    run_clean chmod 0644 "$snapshot/state"
    # `current` is snapshotted like any other managed artifact, BEFORE it is overwritten, so a
    # rollback restores the pointer as well as the files. Its own prior absence counts: on a first
    # deployment there is no current runtime, and rollback must return to that.
    _snapshot_artifact current "$TC_SNAPSHOT_DIR/current" "$snapshot"
    printf '%s\n' "$sha" > "$TC_SNAPSHOT_DIR/previous"
    run_clean chmod 0644 "$TC_SNAPSHOT_DIR/previous"
    phase "snapshot" ok
    note "root-owned snapshot at $snapshot"
    note "prior state: $(tr '\n' ' ' < "$snapshot/state")"

    # From ROOT'S copy. Never from the release — that is the laundering this exists to stop.
    run_clean install -m 0755 -o root -g root "$PREFIX/wp-integrity-scan.sh" "$TC_INSPECTOR_DEST" \
        || die "could not install the inspector"
    phase "install-inspector" ok
    note "$TC_INSPECTOR_DEST installed from $PREFIX/wp-integrity-scan.sh"

    write_sudoers "$snapshot" || return "$EXIT_REFUSED"
    phase "install-sudoers" ok

    # Blocker 1. The complete runtime, into storage the service user cannot write.
    materialize_runtime "$sha" "$release"
    phase "materialize-runtime" ok
    note "$TC_RUNTIME_DIR/$sha is root-owned, go-w stripped, manifest recorded"

    # Root's OWN comparison against the commit. Ownership makes the bytes immutable from here;
    # this is what makes them the right bytes.
    verify_against_commit "$sha" "$TC_RUNTIME_DIR/$sha"
    phase "authenticate-runtime" ok
    note "every file matches commit $sha as read from the object store by root"

    # Immediately before the unit is written and the service consumes it. The tree is root-owned
    # by now, so this cannot fail for benign reasons — which is exactly why it is worth doing.
    verify_runtime "$sha"
    phase "verify-runtime" ok
    note "$(wc -l < "$TC_RUNTIME_DIR/$sha.manifest") files match the root-owned runtime manifest"

    # Only now is there a runtime worth pointing at. `current` is what start-run executes from,
    # so it must never name a tree that failed verification.
    printf '%s\n' "$sha" > "$TC_SNAPSHOT_DIR/current"
    run_clean chmod 0644 "$TC_SNAPSHOT_DIR/current"

    local interpreter
    interpreter="$(resolve_interpreter "$sha")" || return "$EXIT_REFUSED"
    phase "verify-interpreter" ok
    note "$interpreter is root-owned and not writable by the service user"

    write_unit "$sha" "$interpreter" || return "$EXIT_REFUSED"
    phase "write-unit" ok
    note "$TC_UNIT_PATH runs $TC_RUNTIME_DIR/$sha — root-owned, not the release tree"

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
$TC_SERVICE_USER ALL=(root) NOPASSWD: $SELF start-run [0-9]*
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
    # WorkingDirectory and ExecStart point at the ROOT-OWNED runtime copy, never at the release
    # tree. That single substitution is what closes blocker 1: the service consumes bytes the
    # service user cannot reach, so there is no window to redirect it in.
    local sha="$1" interpreter="$2" staged="$TC_SNAPSHOT_DIR/unit.next"
    cat > "$staged" <<UNIT
[Unit]
Description=TC Operations Console ($TC_SERVICE)
After=network.target

[Service]
User=$TC_SERVICE_USER
WorkingDirectory=$TC_RUNTIME_DIR/$sha/orchestrator
Environment=TC_CONSOLE_PORT=$TC_CONSOLE_PORT
Environment=TC_BUILD_COMMIT=$sha
${TC_STORE_DB:+Environment=TC_DB_PATH=$TC_STORE_DB}
${TC_CONSOLE_ENV_FILE:+EnvironmentFile=-$TC_CONSOLE_ENV_FILE}
ExecStart=$interpreter -m tc_growth.cli console $TC_CONSOLE_PORT
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
    run_clean install -m 0644 -o root -g root "$staged" "$TC_UNIT_PATH" \
        || die "could not install the unit file"
}

_snapshot_artifact() {
    local name="$1" path="$2" snapshot="$3"
    if [ -e "$path" ]; then
        run_clean cp -a "$path" "$snapshot/$name.prev" || die "could not snapshot $name"
        printf '%s=present\n' "$name" >> "$snapshot/state"
    else
        printf '%s=absent\n' "$name" >> "$snapshot/state"
    fi
}

_prior_state() {
    local name="$1" snapshot="$2" line
    line="$(grep -m1 "^$name=" "$snapshot/state" 2>/dev/null)" || return 1
    printf '%s\n' "${line#*=}"
}

#: Set by _restore_artifact so the terminal report can distinguish full from partial.
ROLLBACK_RESTORED=0
ROLLBACK_REMOVED=0
ROLLBACK_FAILED=0

_restore_artifact() {
    # Restores prior BYTES when the artifact existed, and prior ABSENCE when it did not. Each
    # artifact reports its own result: "rollback ok" that quietly skipped a removal is the
    # partial-restoration-reported-as-success defect.
    local name="$1" path="$2" mode="$3" snapshot="$4" state
    state="$(_prior_state "$name" "$snapshot")" || {
        phase "rollback-$name" unknown
        note "the snapshot records no prior state for $name — refusing to guess"
        ROLLBACK_FAILED=$((ROLLBACK_FAILED + 1))
        return 0
    }
    case "$state" in
        present)
            if [ ! -f "$snapshot/$name.prev" ]; then
                phase "rollback-$name" failed
                note "prior state was 'present' but $snapshot/$name.prev is missing"
                ROLLBACK_FAILED=$((ROLLBACK_FAILED + 1))
                return 0
            fi
            if run_clean install -m "$mode" -o root -g root "$snapshot/$name.prev" "$path"; then
                phase "rollback-$name" restored
                ROLLBACK_RESTORED=$((ROLLBACK_RESTORED + 1))
            else
                phase "rollback-$name" failed
                ROLLBACK_FAILED=$((ROLLBACK_FAILED + 1))
            fi ;;
        absent)
            if [ ! -e "$path" ]; then
                phase "rollback-$name" already-absent
                ROLLBACK_REMOVED=$((ROLLBACK_REMOVED + 1))
            elif run_clean rm -f "$path"; then
                phase "rollback-$name" removed
                note "$path did not exist before apply; rollback removed it"
                ROLLBACK_REMOVED=$((ROLLBACK_REMOVED + 1))
            else
                phase "rollback-$name" failed
                ROLLBACK_FAILED=$((ROLLBACK_FAILED + 1))
            fi ;;
        *)
            phase "rollback-$name" unknown
            note "unreadable prior state '$state'"
            ROLLBACK_FAILED=$((ROLLBACK_FAILED + 1)) ;;
    esac
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
    [ -f "$snapshot/state" ] || die "the snapshot records no prior state; refusing to roll back blind"
    phase "verify-machinery" ok
    phase "select-snapshot" ok
    note "restoring from $snapshot (selected by root-written pointer, not by the caller)"

    _restore_artifact unit "$TC_UNIT_PATH" 0644 "$snapshot"
    _restore_artifact inspector "$TC_INSPECTOR_DEST" 0755 "$snapshot"
    _restore_artifact sudoers "$TC_SUDOERS_FILE" 0440 "$snapshot"
    _restore_artifact current "$TC_SNAPSHOT_DIR/current" 0644 "$snapshot"

    # Sudoers is validated AFTER the fact, whichever way it went: a restored file must parse, and
    # a removed one must leave the directory parsing. A broken drop-in locks the operator out.
    if command -v visudo >/dev/null; then
        if [ -f "$TC_SUDOERS_FILE" ]; then
            if run_clean visudo -c -f "$TC_SUDOERS_FILE" >/dev/null; then
                phase "validate-sudoers" ok
            else
                phase "validate-sudoers" failed
                note "the restored sudoers drop-in does not parse — inspect $TC_SUDOERS_FILE"
                ROLLBACK_FAILED=$((ROLLBACK_FAILED + 1))
            fi
        else
            phase "validate-sudoers" not-present
            note "nothing to validate: the drop-in was removed because it did not exist before apply"
        fi
    else
        phase "validate-sudoers" unavailable
        note "visudo is not installed here, so the result was NOT syntax-validated"
    fi

    if [ "$ROLLBACK_FAILED" -gt 0 ]; then
        phase "rollback" partial
        note "restored=$ROLLBACK_RESTORED removed=$ROLLBACK_REMOVED failed=$ROLLBACK_FAILED"
        note "this is NOT a completed rollback; the artifacts above say which parts stand."
        return "$EXIT_REFUSED"
    fi
    phase "rollback" complete
    note "restored=$ROLLBACK_RESTORED removed=$ROLLBACK_REMOVED failed=0"

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

verb_bootstrap() {
    # Review blocker: `start-run` refuses until a root-owned `current` runtime exists, but
    # `start-run` is what launches the runner that creates one. On a fresh host that is circular,
    # and the answer "do the first deployment from the terminal" reintroduces exactly the manual
    # burden this work package exists to remove.
    #
    # So the trusted runner runtime is established ONCE, by the owner, during host setup — the
    # same act that installs this program. It materialises and authenticates a runtime and sets
    # `current`, and it touches NOTHING else: no unit, no inspector, no sudoers, no restart. It is
    # not a deployment and must not be able to become one.
    #
    # It is deliberately not in the sudoers surface. The service user can never reach it; only a
    # human already running as root can, which is what makes it a setup step rather than a second
    # way to deploy.
    local sha="$1" release
    valid_sha "$sha" || die "bootstrap takes an exact 40-character lowercase hex SHA"
    release="$TC_RELEASES_DIR/$sha"
    [ -d "$release" ] || die "no release directory for $sha under the configured releases root; \
stage the release worktree as part of host setup, then bootstrap it"

    if [ -f "$TC_SNAPSHOT_DIR/current" ]; then
        die "this target already has a trusted runtime; bootstrap is a one-time setup action and \
refuses to replace one. Deploy through apply instead."
    fi

    phase "verify-machinery" ok
    run_clean install -d -m 0755 -o root -g root "$TC_SNAPSHOT_DIR" || die "cannot create $TC_SNAPSHOT_DIR"
    materialize_runtime "$sha" "$release"
    phase "materialize-runtime" ok
    verify_against_commit "$sha" "$TC_RUNTIME_DIR/$sha"
    phase "authenticate-runtime" ok
    verify_runtime "$sha"
    phase "verify-runtime" ok
    printf '%s\n' "$sha" > "$TC_SNAPSHOT_DIR/current"
    run_clean chmod 0644 "$TC_SNAPSHOT_DIR/current"
    phase "bootstrap" ok
    note "the trusted runner runtime is $TC_RUNTIME_DIR/$sha"
    note "no unit, inspector, sudoers or service state was touched — this is not a deployment."
    note "start-run can now launch the deployment runner from immutable code."
    return 0
}

verb_start_run() {
    # Review blocker 1, both halves.
    #
    # Reachability: the sudoers drop-in now grants exactly `start-run [0-9]*`. The pattern makes
    # the first character a digit and the program re-validates the whole argument below — two
    # layers, because a sudoers `*` matches more than people expect and the program is the one
    # that can be strict. `systemd-run` itself is never granted; the transient unit is created
    # only through this entry point (issue #77 Decision 2).
    #
    # What it runs: NOT the service-user-writable checkout. The runner is unprivileged, but "the
    # unprivileged half" is not a licence to execute mutable code from a unit root created — that
    # is how the boundary ends one process early. It runs from a root-owned materialised runtime
    # and the verified interpreter, or it does not run at all.
    local run_id="$1" current runtime interpreter
    case "$run_id" in ''|*[!0-9]*) die "start-run takes a numeric run id and nothing else" ;; esac

    [ -f "$TC_SNAPSHOT_DIR/current" ] || die \
        "no deployment has been applied on this target yet, so there is no root-owned runtime to "\
"run the deployment runner from. Perform the first deployment from the terminal; after that this "\
"verb has an immutable code path to use."
    _assert_root_owned_and_locked "$TC_SNAPSHOT_DIR/current"
    current="$(cat "$TC_SNAPSHOT_DIR/current")"
    valid_sha "$current" || die "the current-runtime pointer is not a SHA: refusing to act on it"
    runtime="$TC_RUNTIME_DIR/$current"
    _assert_root_owned_and_locked "$runtime"
    verify_runtime "$current"
    phase "verify-runtime" ok
    note "the runner will execute from $runtime, which the service user cannot write"

    interpreter="$(resolve_interpreter "$current")" || return "$EXIT_REFUSED"
    phase "verify-interpreter" ok

    [ -d /run/systemd/system ] || {
        phase "transient-unit" unavailable
        note "systemd is not booted here; no transient unit was created."
        note "the command it WOULD have run: $interpreter -m tc_growth.cli deploy-run $run_id"
        note "  working directory: $runtime/orchestrator"
        return "$EXIT_SYSTEMD_ABSENT"
    }
    run_clean systemd-run --collect --unit="$TC_UNIT_PREFIX-run-$run_id" \
        --uid="$TC_SERVICE_USER" --working-directory="$runtime/orchestrator" \
        --setenv=TC_DB_PATH="$TC_STORE_DB" \
        "$interpreter" -m tc_growth.cli deploy-run "$run_id" \
        || die "could not create the transient deployment unit"
    phase "transient-unit" ok
    note "$TC_UNIT_PREFIX-run-$run_id created, running from the root-owned runtime"
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
    bootstrap)  [ $# -eq 2 ] || die "bootstrap takes exactly one argument, the target SHA"; verb_bootstrap "$2" ;;
    start-run)  [ $# -eq 2 ] || die "start-run takes exactly one argument, the run id"; verb_start_run "$2" ;;
    *)          die "not a verb: '${1-}' (the interface is: self-check, apply <sha>, rollback, start-run <id>, bootstrap <sha>)" ;;
esac
