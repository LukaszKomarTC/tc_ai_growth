#!/bin/bash
# Operations Console — single reviewed deployment operation (WP-CONSOLE-MVP).
#
# The whole point of the Console is to END blind terminal copy-paste. So its OWN first deployment
# is packaged as ONE inspectable script with preflight → snapshot → install → service → health
# check → rollback, pinned to a fixed release commit. Read it top to bottom before running; it
# changes NOTHING unless you pass --apply (default is a dry run that prints every action).
#
# It deploys two things and wires them to run the SAME code the repo reviewed:
#   1. the Technical Inspector script  -> /usr/local/bin (atomic, hash-stamped)
#   2. the Operations Console          -> a loopback systemd service (token-gated, fail-closed)
# Cron and the Console then invoke the identical deployed inspector (no drift; see
# docs/TECHNICAL_INSPECTOR.md and docs/workpackages/WP-CONSOLE-DEPLOYMENT.md).
#
# Usage:
#   ./deploy-console.sh                 # DRY RUN — prints the plan/delta, changes nothing
#   ./deploy-console.sh --apply         # perform the deployment
#   ./deploy-console.sh --rollback      # restore the most recent snapshot
#
# RELEASE-DIRECTORY DEPLOYMENT (D1): this script deploys THE CHECKOUT IT LIVES IN. Run it from an
# isolated release checkout (e.g. a detached git worktree pinned at the reviewed commit under
# /opt/tc_ai_growth/console or /opt/tc_ai_growth/releases/<sha>) — NEVER from the production-
# scheduled checkout that tc-weekly-report/tc-autodeploy run from; preflight refuses that.
# Bootstrap (as the service user):  git fetch origin <branch>
#                                   git worktree add --detach <release-dir> <reviewed-sha>
# then copy orchestrator/.env into the release dir, set TC_VENV to the shared venv, and run this
# script from <release-dir>/orchestrator.
#
# Redeploy semantics (see docs/workpackages/WP-CONSOLE-DEPLOYMENT.md for the full Q&A):
#   * Idempotent / safe to run twice: each run snapshots first, overwrites the unit + inspector,
#     and RESTARTS the service (enable+restart — `enable --now` alone would leave old code live
#     on a running service, D5b). Re-running with the same commit redeploys identical state.
#   * Snapshots are timestamped and RETAINED under $SNAP_DIR (previous states kept for rollback).
#   * A redeploy INVALIDATES active Console sessions (the session signature is bound to the deploy
#     commit) — a code change on an execution surface forces re-auth.
#   * Health check fails after activation -> the script aborts and points you at --rollback.
#   * To deploy a NEWER reviewed commit: advance the detached worktree
#     (git fetch && git checkout --detach <new-sha>) and re-run. Atomic symlink swap between
#     release dirs remains recorded debt in the deployment runbook.
set -uo pipefail

# ---- configuration (override via env; confirm these match YOUR box before --apply) ----
# Default APP_DIR = the orchestrator/ directory of THE CHECKOUT CONTAINING THIS SCRIPT — you
# deploy what you run from (D1). The venv is usually shared from the main install, so TC_VENV
# must be set explicitly when deploying from a release dir that has no .venv of its own.
SCRIPT_SELF="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${TC_APP_DIR:-$(dirname "$SCRIPT_SELF")}"              # orchestrator/ of this checkout
VENV="${TC_VENV:-$APP_DIR/.venv}"                               # its virtualenv
SERVICE_USER="${TC_SERVICE_USER:-tcgrowth}"                     # unprivileged runtime user
CONSOLE_PORT="${TC_CONSOLE_PORT:-8385}"                         # loopback port
INSPECTOR_DEST="${TC_INSPECTOR_SCRIPT:-/usr/local/bin/wp-integrity-scan.sh}"
CONSOLE_ENV_FILE="${TC_CONSOLE_ENV_FILE:-/etc/tc-console.env}"  # holds TC_CONSOLE_TOKEN etc.
SNAP_DIR="${TC_SNAP_DIR:-/var/backups/tc-console}"
UNIT="/etc/systemd/system/tc-console.service"
# Scan permission (D2): the service user cannot read the WP docroot, so the Console runs the
# inspector through ONE narrowly-scoped sudo rule: exactly this root-owned script, ZERO arguments,
# nothing else. Installed below as a validated sudoers.d drop-in; shown in the plan.
SUDOERS_FILE="/etc/sudoers.d/tc-console-scan"
RELEASE_BRANCH="${TC_RELEASE_BRANCH:-main}"  # reviewed branch for identity check (main since the Console merge)
# RELEASE_COMMIT is resolved AFTER the owner-run git wrapper (rgit) exists — a plain root git here
# hits dubious-ownership on the tcgrowth-owned checkout and silently pinned "unknown" into
# TC_BUILD_COMMIT, poisoning evidence provenance. Env override wins; otherwise derived = GIT_SHA.
RELEASE_COMMIT="${TC_BUILD_COMMIT:-}"

APPLY=0; ROLLBACK=0
case "${1:-}" in
  --apply) APPLY=1 ;;
  --rollback) ROLLBACK=1 ;;
  ""|--dry-run) APPLY=0 ;;
  *) echo "usage: $0 [--apply|--rollback|--dry-run]"; exit 2 ;;
esac

say(){ printf '\n\033[1m== %s\033[0m\n' "$*"; }
# EVERY mutation goes through run(): in --apply it echoes then executes; in dry-run it only prints.
# So the dry-run output IS the apply action list — there is no second, separate description of what
# happens (review: dry-run and apply must be generated from the same plan data).
run(){ if [ "$APPLY" = 1 ]; then echo "+ $*"; "$@"; else echo "[dry-run] $*"; fi; }
die(){ printf '\033[31mABORT:\033[0m %s\n' "$*" >&2; exit 1; }

# Mutating steps as named functions so they are single actions run() can print AND execute — no
# apply-only command escapes the dry-run listing.
write_console_unit(){ printf '%s\n' "$UNIT_CONTENT" > "$UNIT"; }
write_sudoers_tmp(){ printf '%s\n' "$SUDOERS_CONTENT" > "$SNAP/sudoers-tc-console-scan"; }
record_deploy(){ local h; h="$(sha256sum "$1" | cut -c1-16)";
  logger -t tc-inspector "deployed $1 sha256=$h commit=$RELEASE_COMMIT";
  echo "  recorded: $1 sha256=$h commit=$RELEASE_COMMIT"; }

STAMP="$(date -u '+%Y%m%d-%H%M%S')"
SNAP="$SNAP_DIR/$STAMP"

# ---------------------------------------------------------------------------
rollback(){
  # D3 fix: rollback IS a mutation pass — earlier versions left APPLY=0 here, so every run()
  # step only PRINTED and rollback silently did nothing. Rollback executes, and still echoes
  # every action through run() so the operator sees exactly what is restored.
  APPLY=1
  [ "$(id -u)" -eq 0 ] || die "run as root for --rollback"
  say "ROLLBACK — restoring the most recent snapshot"
  local last; last="$(ls -1d "$SNAP_DIR"/*/ 2>/dev/null | tail -1)"
  [ -n "$last" ] || die "no snapshot found under $SNAP_DIR"
  echo "restoring from $last"
  if [ -f "$last/tc-console.service" ]; then
    run cp -a "$last/tc-console.service" "$UNIT"
    run systemctl daemon-reload
    run systemctl restart tc-console.service
  else
    # First-install rollback: there was no unit before, so remove what the deploy created.
    run systemctl disable --now tc-console.service
    run rm -f "$UNIT"
    run systemctl daemon-reload
  fi
  # cp -a preserves the snapshotted mode/owner — restores exactly what was there before.
  [ -f "$last/wp-integrity-scan.sh" ] && run cp -a "$last/wp-integrity-scan.sh" "$INSPECTOR_DEST"
  if [ -f "$last/sudoers-tc-console-scan.prev" ]; then
    run cp -a "$last/sudoers-tc-console-scan.prev" "$SUDOERS_FILE"
  else
    # No sudoers rule existed before this deploy — remove the one the deploy installed.
    [ -f "$SUDOERS_FILE" ] && run rm -f "$SUDOERS_FILE"
  fi
  [ -f "$last/store.sqlite3" ] && echo "NOTE: prior store DB preserved at $last/store.sqlite3 (restore by hand if needed)"
  echo "rollback complete."
  exit 0
}
[ "$ROLLBACK" = 1 ] && rollback

# ---------------------------------------------------------------------------
say "Phase 1 — preflight (read-only checks)"
[ "$APPLY" = 1 ] && [ "$(id -u)" -ne 0 ] && die "run as root for --apply (systemd + /usr/local/bin)"
[ -d "$APP_DIR" ] || die "APP_DIR not found: $APP_DIR (set TC_APP_DIR)"
[ -x "$VENV/bin/python" ] || die "venv python not found: $VENV/bin/python (set TC_VENV to the shared venv when deploying from a release dir)"
id "$SERVICE_USER" >/dev/null 2>&1 || die "service user missing: $SERVICE_USER (set TC_SERVICE_USER)"
[ -f "$APP_DIR/scripts/wp-integrity-scan.sh" ] || die "repo inspector script missing under $APP_DIR/scripts"
# D1 guard: NEVER deploy from the checkout that production schedules run from — switching or
# reusing it would silently change what the weekly report / autodeploy execute.
for prod_unit in tc-weekly-report.service tc-autodeploy.service; do
  if systemctl cat "$prod_unit" 2>/dev/null | grep -q "$APP_DIR"; then
    die "APP_DIR $APP_DIR is referenced by $prod_unit — deploy from an ISOLATED release checkout (git worktree --detach <sha>), never the production-scheduled one"
  fi
done
# Deterministic module resolution for the checks below: with the shared venv's editable install,
# cwd wins on sys.path, so run all python from the release checkout being deployed.
cd "$APP_DIR" || die "cannot cd to $APP_DIR"
# The console must have a token, or it fails closed. Never generate+print a secret here.
if [ ! -f "$CONSOLE_ENV_FILE" ] || ! grep -q '^TC_CONSOLE_TOKEN=' "$CONSOLE_ENV_FILE" 2>/dev/null; then
  die "no TC_CONSOLE_TOKEN in $CONSOLE_ENV_FILE — create it first (chmod 600), e.g.:
       umask 077; printf 'TC_CONSOLE_TOKEN=%s\n' \"\$(openssl rand -base64 32)\" >> $CONSOLE_ENV_FILE"
fi
"$VENV/bin/python" -m tc_growth.cli list-operations >/dev/null 2>&1 \
  || die "registry does not validate under the deployed venv — fix before deploying"
# D5: on a REDEPLOY the port is legitimately held by the running tc-console itself (it gets
# restarted in phase 4). Only a FOREIGN listener is a conflict.
if ss -ltn 2>/dev/null | grep -q ":$CONSOLE_PORT "; then
  if systemctl is-active --quiet tc-console.service; then
    echo "port $CONSOLE_PORT is held by the running tc-console service — this deploy will restart it."
  else
    die "port $CONSOLE_PORT is in use by something OTHER than tc-console — investigate before deploying"
  fi
fi

# Deployment identity — what gets deployed is whatever is checked out HERE, so the plan must
# prove it is the reviewed revision: branch/commit, clean tree, and agreement with the remote.
# A dirty tree is REJECTED for --apply (the deployed code would not match any reviewed commit).
# Release checkouts are DETACHED worktrees pinned at the reviewed sha, so the check verifies the
# pinned commit against origin/$RELEASE_BRANCH rather than assuming a local branch.
REPO_DIR="$(cd "$APP_DIR/.." && pwd)"
# D5 hardening: NEVER run git as root inside a service-user-owned checkout — `git status` can
# rewrite the index root-owned, breaking the owner's future fetch/checkout (this exact failure
# happened on the first redeploy). All identity-check git runs as the checkout's OWNER.
REPO_OWNER="$(stat -c %U "$REPO_DIR" 2>/dev/null || echo root)"
rgit(){ if [ "$(id -u)" -eq 0 ] && [ "$REPO_OWNER" != "root" ]; then
          sudo -n -u "$REPO_OWNER" git -C "$REPO_DIR" "$@"
        else
          git -C "$REPO_DIR" "$@"
        fi; }
GIT_BRANCH="$(rgit rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
GIT_SHA="$(rgit rev-parse HEAD 2>/dev/null || echo unknown)"
# Pin the source commit from the same owner-run identity check the plan displays (unless the
# operator overrode it via TC_BUILD_COMMIT). "unknown" is now impossible when the checkout is
# readable — and an unreadable checkout fails the identity fields visibly right above.
RELEASE_COMMIT="${RELEASE_COMMIT:-$GIT_SHA}"
if [ -z "$(rgit status --porcelain 2>/dev/null)" ]; then TREE_STATE="clean"; else TREE_STATE="DIRTY"; fi
REMOTE_STATE="not checked (no network / no upstream)"
CHECK_BRANCH="$GIT_BRANCH"
if [ "$GIT_BRANCH" = "HEAD" ]; then
  GIT_BRANCH="(detached — release checkout pinned at commit)"
  CHECK_BRANCH="$RELEASE_BRANCH"
fi
if rgit fetch -q origin "$CHECK_BRANCH" 2>/dev/null; then
  ORIGIN_TIP="$(rgit rev-parse "origin/$CHECK_BRANCH" 2>/dev/null || echo none)"
  if [ "$ORIGIN_TIP" = "$GIT_SHA" ]; then
    REMOTE_STATE="matches origin/$CHECK_BRANCH tip"
  elif rgit merge-base --is-ancestor "$GIT_SHA" "$ORIGIN_TIP" 2>/dev/null; then
    REMOTE_STATE="on origin/$CHECK_BRANCH but BEHIND its tip — confirm this older commit is the reviewed release"
  else
    REMOTE_STATE="NOT on origin/$CHECK_BRANCH — do not deploy unreviewed code"
  fi
fi
if [ "$TREE_STATE" = "DIRTY" ]; then
  if [ "$APPLY" = 1 ]; then
    die "working tree is DIRTY — deploying it would not match any reviewed commit. Commit/stash first."
  else
    echo "WARNING: working tree is DIRTY — --apply will be refused until it is clean."
  fi
fi
echo "preflight OK."

# ---------------------------------------------------------------------------
# The plan — readable at the level of business impact, printed on EVERY run (dry or apply) so the
# owner sees the exact delta before deciding, not just "preflight passed".
CUR_UNIT_STATE="absent"; [ -f "$UNIT" ] && CUR_UNIT_STATE="present (will be REPLACED)"
CUR_INSP_STATE="absent"; [ -f "$INSPECTOR_DEST" ] && CUR_INSP_STATE="present (will be REPLACED)"
CUR_SUDO_STATE="absent (will be CREATED)"; [ -f "$SUDOERS_FILE" ] && CUR_SUDO_STATE="present (will be REPLACED)"
# The one permission grant (D2): exact path, zero arguments ("" in sudoers = no args allowed).
SUDOERS_CONTENT="$SERVICE_USER ALL=(root) NOPASSWD: $INSPECTOR_DEST \"\""
NEW_HASH="$(sha256sum "$APP_DIR/scripts/wp-integrity-scan.sh" 2>/dev/null | cut -c1-16)"
say "DEPLOYMENT PLAN — review before --apply"
cat <<PLAN
  Release checkout (APP_DIR) .... $APP_DIR
  Branch ........................ $GIT_BRANCH
  Commit ........................ $GIT_SHA
  Working tree .................. $TREE_STATE
  Remote state .................. $REMOTE_STATE
  Source commit pinned .......... $RELEASE_COMMIT
  Python venv (shared) .......... $VENV
  Inspector script .............. $APP_DIR/scripts/wp-integrity-scan.sh  (sha256 ${NEW_HASH}…)
      -> installed to ........... $INSPECTOR_DEST  mode 0755 root-owned  [$CUR_INSP_STATE]
  Scan permission (sudoers) ..... $SUDOERS_FILE   [$CUR_SUDO_STATE]
      exact rule ................ $SUDOERS_CONTENT
      (ONE fixed root-owned script, ZERO arguments, nothing else; sudo strips the caller's
       environment, so the scan target cannot be overridden by the Console either)
  systemd unit .................. $UNIT   [$CUR_UNIT_STATE]
  Runs as user .................. $SERVICE_USER   (unprivileged; sudo limited to the one rule above)
  Bind address / port ........... 127.0.0.1:$CONSOLE_PORT   (loopback only — NOT internet-exposed)
  Reads secrets from ............ $CONSOLE_ENV_FILE   (READ only — this script never writes it)
  Backup / snapshot to .......... $SNAP
  Restarts an existing service .. $( [ "$CUR_UNIT_STATE" = absent ] && echo "no (first install)" || echo "YES — tc-console will restart; active browser sessions are invalidated on redeploy" )
  Modifies any .env / profiles .. NO
  Touches production WordPress ... NO  (deploys the Console + read-only inspector only; never the site)
  Rollback command .............. $0 --rollback   (restores unit, inspector, and sudoers state)
PLAN

say "Phase 2 — snapshot (so rollback is real)"
run mkdir -p "$SNAP"
[ -f "$UNIT" ] && run cp -a "$UNIT" "$SNAP/tc-console.service"
[ -f "$INSPECTOR_DEST" ] && run cp -a "$INSPECTOR_DEST" "$SNAP/wp-integrity-scan.sh"
[ -f "$SUDOERS_FILE" ] && run cp -a "$SUDOERS_FILE" "$SNAP/sudoers-tc-console-scan.prev"
# best-effort copy of the evidence store so a bad deploy can't lose history
STORE="${TC_STORE_PATH:-$APP_DIR/var/store.sqlite3}"
[ -f "$STORE" ] && run cp -a "$STORE" "$SNAP/store.sqlite3"
echo "snapshot dir: $SNAP"

say "Phase 3 — deploy the inspector atomically (single source of truth)"
# 0755, root-owned: world-READABLE so the service user can hash it for provenance, but only
# root can modify what the sudo rule lets it execute.
run install -m0755 -o root -g root "$APP_DIR/scripts/wp-integrity-scan.sh" "$INSPECTOR_DEST"
run record_deploy "$INSPECTOR_DEST"

say "Phase 3b — install the scan permission (validated sudoers drop-in)"
run mkdir -p "$SNAP"                      # dry-run shows it; apply already created it in phase 2
run write_sudoers_tmp                     # writes the rule to $SNAP/sudoers-tc-console-scan
run visudo -c -f "$SNAP/sudoers-tc-console-scan"   # syntax-validate BEFORE it can take effect
run install -m0440 -o root -g root "$SNAP/sudoers-tc-console-scan" "$SUDOERS_FILE"

say "Phase 4 — configure the Console service (loopback, token-gated)"
UNIT_CONTENT="$(cat <<UNIT_EOF
[Unit]
Description=TC Operations Console (loopback execution surface)
After=network.target

[Service]
User=$SERVICE_USER
# WorkingDirectory = the release checkout: with the shared venv's editable install, cwd wins on
# sys.path, so the service runs THIS release's code.
WorkingDirectory=$APP_DIR
EnvironmentFile=$CONSOLE_ENV_FILE
Environment=TC_BUILD_COMMIT=$RELEASE_COMMIT
Environment=TC_INSPECTOR_SCRIPT=$INSPECTOR_DEST
# Integrity scan runs via the single sudoers-allowlisted command (see $SUDOERS_FILE).
Environment=TC_INSPECTOR_SUDO=true
# Bind loopback only; remote access is an SSH tunnel, never a public port.
ExecStart=$VENV/bin/python -m tc_growth.cli console $CONSOLE_PORT
Restart=on-failure
# Hardening posture, chosen deliberately:
#  - NoNewPrivileges is OFF: it would block sudo's setuid, and the scan permission model IS the
#    one narrowly-scoped sudo rule. The sudoers allowlist (exact path, zero args) is the control.
#  - ProtectSystem=full (not strict): /usr /boot /etc stay read-only; strict also made /run and
#    /var/log read-only, which breaks sudo's timestamp dir and the scanner's own log file.
#  - PrivateTmp stays ON: the scanner's /tmp lock is then per-service, so it guards against the
#    Console stacking its own scans; cron's lock lives in the real /tmp. A rare Console+cron
#    overlap is two read-only scans — harmless by design.
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT_EOF
)"
echo "  unit to be written to $UNIT:"; printf '%s\n' "$UNIT_CONTENT" | sed 's/^/    | /'
run install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$APP_DIR/var"   # default store/evidence dir
run write_console_unit                       # writes $UNIT (printed as a step in dry-run too)
run systemctl daemon-reload
run systemctl enable tc-console.service
# D5b: `enable --now` does NOT restart an already-running service, so a redeploy would keep the
# OLD code live. restart covers both cases: starts a stopped service, restarts a running one.
run systemctl restart tc-console.service

say "Phase 5 — health check"
if [ "$APPLY" = 1 ]; then
  sleep 1
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$CONSOLE_PORT/" || echo 000)"
  [ "$code" = 200 ] || { echo "health check FAILED (HTTP $code)"; echo "see: journalctl -u tc-console -n50"; die "not healthy — consider --rollback"; }
  echo "health check OK — login page served (HTTP 200) on loopback"
else
  echo "[dry-run] would curl http://127.0.0.1:$CONSOLE_PORT/ and expect HTTP 200 (login page)"
fi

say "Phase 6 — access"
cat <<ACCESS

  Operations Console deployed (commit $RELEASE_COMMIT), listening on 127.0.0.1:$CONSOLE_PORT.
  It is NOT internet-exposed. Reach it from your machine over an SSH tunnel:

      ssh -L $CONSOLE_PORT:127.0.0.1:$CONSOLE_PORT $SERVICE_USER@<vps-host>
      # then open:  http://localhost:$CONSOLE_PORT

  Sign in with the token in $CONSOLE_ENV_FILE. Rollback anytime:  $0 --rollback
ACCESS
[ "$APPLY" = 0 ] && echo "
(DRY RUN — nothing was changed. Re-run with --apply once the config above matches your box.)"
