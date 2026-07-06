#!/usr/bin/env bash
# Pull-based auto-deploy (GitOps) for the TC AI Operations Platform.
#
# Runs as the tcgrowth user every few minutes (tc-autodeploy.timer). If origin/main has new
# commits: pull, reinstall, run the FULL test suite, and only then restart the dashboard.
# If tests fail, roll back to the previous commit and reinstall — the running system never
# serves a broken main. Every step is logged to orchestrator/data/autodeploy.log.
#
# This removes the human copy-paste deploy loop WITHOUT granting anyone shell access:
# merges to main deploy themselves; humans review outcomes.
# Kill switch: systemctl disable --now tc-autodeploy.timer

set -u
APP="/opt/tc_ai_growth/app"
LOG="$APP/orchestrator/data/autodeploy.log"
PY="$APP/.venv/bin/python"
PIP="$APP/.venv/bin/pip"

log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }

cd "$APP" || { log "FATAL: $APP missing"; exit 1; }
mkdir -p "$APP/orchestrator/data"

git fetch origin main --quiet 2>>"$LOG" || { log "fetch failed"; exit 1; }
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
[ "$LOCAL" = "$REMOTE" ] && exit 0   # nothing new — silent

log "deploying $LOCAL -> $REMOTE"
git pull --ff-only origin main --quiet 2>>"$LOG" || { log "pull failed (non-ff?)"; exit 1; }

install() { "$PIP" install -q -e "$APP/orchestrator[anthropic,google,dev]" >>"$LOG" 2>&1; }

install || { log "install failed — rolling back"; git checkout -q "$LOCAL"; install; exit 1; }

if (cd "$APP/orchestrator" && "$PY" -m pytest -q >>"$LOG" 2>&1); then
    log "tests green — restarting dashboard"
    # Needs the one-line sudoers rule from deployments/systemd/README.md (restart only, no shell).
    sudo -n systemctl restart tc-dashboard.service 2>>"$LOG" || log "dashboard restart failed (sudoers rule missing?)"
    log "deployed $REMOTE OK"
else
    log "TESTS FAILED on $REMOTE — ROLLING BACK to $LOCAL"
    git checkout -q "$LOCAL"
    install
    log "rollback complete; main is broken and needs a fix commit"
fi
