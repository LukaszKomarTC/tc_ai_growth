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
#   ./deploy-console.sh                 # DRY RUN — prints what it would do, changes nothing
#   ./deploy-console.sh --apply         # perform the deployment
#   ./deploy-console.sh --rollback      # restore the most recent snapshot
set -uo pipefail

# ---- configuration (override via env; confirm these match YOUR box before --apply) ----
APP_DIR="${TC_APP_DIR:-/opt/tc_ai_growth/app/orchestrator}"     # where the orchestrator lives
VENV="${TC_VENV:-$APP_DIR/.venv}"                               # its virtualenv
SERVICE_USER="${TC_SERVICE_USER:-tcgrowth}"                     # unprivileged runtime user
CONSOLE_PORT="${TC_CONSOLE_PORT:-8385}"                         # loopback port
INSPECTOR_DEST="${TC_INSPECTOR_SCRIPT:-/usr/local/bin/wp-integrity-scan.sh}"
CONSOLE_ENV_FILE="${TC_CONSOLE_ENV_FILE:-/etc/tc-console.env}"  # holds TC_CONSOLE_TOKEN etc.
SNAP_DIR="${TC_SNAP_DIR:-/var/backups/tc-console}"
UNIT="/etc/systemd/system/tc-console.service"
RELEASE_COMMIT="${TC_BUILD_COMMIT:-$(git -C "$APP_DIR/.." rev-parse --short HEAD 2>/dev/null || echo unknown)}"

APPLY=0; ROLLBACK=0
case "${1:-}" in
  --apply) APPLY=1 ;;
  --rollback) ROLLBACK=1 ;;
  ""|--dry-run) APPLY=0 ;;
  *) echo "usage: $0 [--apply|--rollback|--dry-run]"; exit 2 ;;
esac

say(){ printf '\n\033[1m== %s\033[0m\n' "$*"; }
run(){ if [ "$APPLY" = 1 ]; then echo "+ $*"; "$@"; else echo "[dry-run] $*"; fi; }
die(){ printf '\033[31mABORT:\033[0m %s\n' "$*" >&2; exit 1; }

STAMP="$(date -u '+%Y%m%d-%H%M%S')"
SNAP="$SNAP_DIR/$STAMP"

# ---------------------------------------------------------------------------
rollback(){
  say "ROLLBACK — restoring the most recent snapshot"
  local last; last="$(ls -1d "$SNAP_DIR"/*/ 2>/dev/null | tail -1)"
  [ -n "$last" ] || die "no snapshot found under $SNAP_DIR"
  echo "restoring from $last"
  [ -f "$last/tc-console.service" ] && run install -m0644 "$last/tc-console.service" "$UNIT"
  [ -f "$last/wp-integrity-scan.sh" ] && run install -m0750 "$last/wp-integrity-scan.sh" "$INSPECTOR_DEST"
  [ -f "$last/store.sqlite3" ] && echo "NOTE: prior store DB preserved at $last/store.sqlite3 (restore by hand if needed)"
  run systemctl daemon-reload
  run systemctl restart tc-console.service
  echo "rollback complete."
  exit 0
}
[ "$ROLLBACK" = 1 ] && rollback

# ---------------------------------------------------------------------------
say "Phase 1 — preflight (read-only checks)"
[ "$APPLY" = 1 ] && [ "$(id -u)" -ne 0 ] && die "run as root for --apply (systemd + /usr/local/bin)"
[ -d "$APP_DIR" ] || die "APP_DIR not found: $APP_DIR (set TC_APP_DIR)"
[ -x "$VENV/bin/python" ] || die "venv python not found: $VENV/bin/python (set TC_VENV)"
id "$SERVICE_USER" >/dev/null 2>&1 || die "service user missing: $SERVICE_USER (set TC_SERVICE_USER)"
[ -f "$APP_DIR/scripts/wp-integrity-scan.sh" ] || die "repo inspector script missing under $APP_DIR/scripts"
# The console must have a token, or it fails closed. Never generate+print a secret here.
if [ ! -f "$CONSOLE_ENV_FILE" ] || ! grep -q '^TC_CONSOLE_TOKEN=' "$CONSOLE_ENV_FILE" 2>/dev/null; then
  die "no TC_CONSOLE_TOKEN in $CONSOLE_ENV_FILE — create it first (chmod 600), e.g.:
       umask 077; printf 'TC_CONSOLE_TOKEN=%s\n' \"\$(openssl rand -base64 32)\" >> $CONSOLE_ENV_FILE"
fi
"$VENV/bin/python" -m tc_growth.cli list-operations >/dev/null 2>&1 \
  || die "registry does not validate under the deployed venv — fix before deploying"
if ss -ltn 2>/dev/null | grep -q ":$CONSOLE_PORT "; then die "port $CONSOLE_PORT already in use"; fi
echo "preflight OK. release commit to deploy: $RELEASE_COMMIT"

say "Phase 2 — snapshot (so rollback is real)"
run mkdir -p "$SNAP"
[ -f "$UNIT" ] && run cp -a "$UNIT" "$SNAP/tc-console.service"
[ -f "$INSPECTOR_DEST" ] && run cp -a "$INSPECTOR_DEST" "$SNAP/wp-integrity-scan.sh"
# best-effort copy of the evidence store so a bad deploy can't lose history
STORE="${TC_STORE_PATH:-$APP_DIR/var/store.sqlite3}"
[ -f "$STORE" ] && run cp -a "$STORE" "$SNAP/store.sqlite3"
echo "snapshot dir: $SNAP"

say "Phase 3 — deploy the inspector atomically (single source of truth)"
run install -m0750 "$APP_DIR/scripts/wp-integrity-scan.sh" "$INSPECTOR_DEST"
if [ "$APPLY" = 1 ]; then
  HASH="$(sha256sum "$INSPECTOR_DEST" | cut -d' ' -f1)"
  logger -t tc-inspector "deployed $INSPECTOR_DEST sha256=${HASH:0:16} commit=$RELEASE_COMMIT"
  echo "deployed inspector sha256=${HASH:0:16} commit=$RELEASE_COMMIT"
fi

say "Phase 4 — configure the Console service (loopback, token-gated)"
UNIT_CONTENT="$(cat <<UNIT_EOF
[Unit]
Description=TC Operations Console (loopback execution surface)
After=network.target

[Service]
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$CONSOLE_ENV_FILE
Environment=TC_BUILD_COMMIT=$RELEASE_COMMIT
Environment=TC_INSPECTOR_SCRIPT=$INSPECTOR_DEST
# Bind loopback only; remote access is an SSH tunnel, never a public port.
ExecStart=$VENV/bin/python -m tc_growth.cli console $CONSOLE_PORT
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$APP_DIR/var
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT_EOF
)"
if [ "$APPLY" = 1 ]; then
  printf '%s\n' "$UNIT_CONTENT" > "$UNIT"
  systemctl daemon-reload
  systemctl enable --now tc-console.service
else
  echo "[dry-run] would write $UNIT:"; printf '%s\n' "$UNIT_CONTENT" | sed 's/^/    /'
fi

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
