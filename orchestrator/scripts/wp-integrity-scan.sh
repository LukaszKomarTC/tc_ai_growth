#!/bin/bash
# Technical Inspector v0 — WordPress integrity monitor
#
# Born from INC-2026-07-27: an 8-day WordPress compromise (spam-mailer + RCE) that signature
# tools kept partially missing. This script runs the SAME checks that (belatedly) surfaced it —
# core/plugin checksums, shell-name patterns, PHP-in-uploads/mu-plugins, kit fingerprints, and
# an administrator-set diff — on a schedule, and emails ONLY when it finds something. Had this
# existed on July 19, the compromise would have alerted on day one, not day eight.
#
# READ-ONLY: it inspects and emails; it never modifies the site.
# Install: see docs/TECHNICAL_INSPECTOR.md
#
# This is the pragmatic first brick of the full (Python, per-profile, snapshot-and-diff)
# Technical Inspector. It is intentionally a standalone shell script so it can run with zero
# platform dependencies while the real Inspector is built.
set -uo pipefail

# --- config (per-site; the full Inspector generalizes this per profile) ---
SITE="${TC_SITE_DOCROOT:-/var/www/vhosts/tossacycling.com/httpdocs}"
ALERT_TO="${TC_ALERT_EMAIL:-info@tossacycling.com}"
EXPECT_ADMINS="${TC_EXPECT_ADMINS:-1,119}"   # sorted, comma-joined WP admin IDs; update on legit change
LOGFILE="${TC_INSPECTOR_LOG:-/var/log/tc-inspector.log}"
# Command that delivers an alert via the platform's authenticated notifier: reads the finding
# on stdin, takes the subject as $1. Empty = notifier not wired (findings still logged).
# e.g. TC_NOTIFY_CMD='sudo -u tcgrowth /opt/tc_ai_growth/app/orchestrator/.venv/bin/python -m tc_growth.cli notify'
NOTIFY_CMD="${TC_NOTIFY_CMD:-}"
# mu-plugins we install ourselves (legit) — allowlisted so the monitor doesn't flag its own kind
MU_ALLOW='index.php|zzz-tc-'
WP="wp --path=$SITE --allow-root"

# prevent overlapping runs (a slow scan must not stack on the next cron tick)
LOCK="/tmp/tc-inspector.lock"
exec 9>"$LOCK" || exit 0
flock -n 9 || { echo "$(date -u '+%F %H:%M UTC') inspector: already running — skipped" >> "$LOGFILE"; exit 0; }

START=$(date +%s)

cd "$SITE" 2>/dev/null || {
  echo "$(date -u '+%F %H:%M UTC') inspector: docroot missing: $SITE" | tee -a "$LOGFILE"
  command -v mail >/dev/null 2>&1 && echo "docroot missing: $SITE" | mail -s "[inspector] docroot missing" "$ALERT_TO"
  exit 1
}

FINDINGS=""
add(){ FINDINGS="${FINDINGS}\n== $1 ==\n$2\n"; }

# 1. WordPress core integrity (official checksums — core is authoritative, any mismatch matters)
CORE=$($WP core verify-checksums 2>&1 | grep -iE "should not exist|does not match")
[ -n "$CORE" ] && add "CORE checksum anomalies" "$CORE"

# 2. repo-plugin integrity — flag EXTRA files only ("should not exist"). "does not match" is
#    dropped on purpose: premium plugins (e.g. shopkeeper-extender) legitimately mismatch the
#    free wp.org edition on every file. Extra planted files are the real signal; modified-file
#    injection into a repo plugin is covered by the fingerprint/hex scans (v1 adds per-file baseline).
PLUG=$($WP plugin verify-checksums --all 2>&1 \
        | grep -iE "should not exist" \
        | grep -viE "Could not retrieve|Couldn't fetch")
[ -n "$PLUG" ] && add "PLUGIN extra/planted files" "$PLUG"

# 3. shell-name pattern: hex-suffixed PHP anywhere in wp-content (the kit's signature naming)
HEX=$(find wp-content -type f -name "*.php" 2>/dev/null | grep -iE "[-_][0-9a-f]{6,8}\.php$")
[ -n "$HEX" ] && add "Hex-suffixed PHP (shell naming)" "$HEX"

# 4. executable PHP where none belongs. uploads: ANY php (never legit except index guards) —
#    the one exception is WP All Import's functions.php, a legitimate code-exec feature that
#    ships EMPTY; flag it only when non-empty (custom functions added, OR a shell planted).
#    mu-plugins: any php that isn't our own allowlisted hardening.
UPL=$(find wp-content/uploads -name "*.php" ! -name index.php 2>/dev/null | while IFS= read -r f; do
  case "$f" in
    */wpallimport/functions.php) [ -s "$f" ] && echo "$f (WP All Import custom-functions — non-empty, review)";;
    *) echo "$f";;
  esac
done)
MU=$(find wp-content/mu-plugins -maxdepth 1 -name "*.php" 2>/dev/null | grep -vE "/($MU_ALLOW)")
[ -n "$UPL$MU" ] && add "Unexpected PHP in uploads/mu-plugins" "$(printf '%s\n%s' "$UPL" "$MU" | sed '/^$/d')"

# 5. known-kit fingerprints + generic dropper markers
FP=$(grep -rlE "phpiAgloq|_wp_cuh_restore|WP_Core_Integrity|_site_transient_health_b5592a35" \
        wp-content wp-includes 2>/dev/null | grep -v duplicator-backups)
[ -n "$FP" ] && add "Known-kit fingerprints" "$FP"

# 6. administrator-set drift (INC-2026-07-27's first artifact was a rogue admin)
ADM=$($WP user list --role=administrator --field=ID 2>/dev/null | sort -n | paste -sd, -)
[ -n "$ADM" ] && [ "$ADM" != "$EXPECT_ADMINS" ] && \
  add "ADMIN set changed" "current: [$ADM]  expected: [$EXPECT_ADMINS] — investigate new IDs with 'wp user get <id>'"

# 7. wp-config injection markers (the breach injected a DB-payload loader here)
WPC=$(grep -nE "eval\(|base64_decode\(|WP_Core_Integrity|auto_prepend_file" wp-config.php 2>/dev/null)
[ -n "$WPC" ] && add "wp-config anomalies" "$WPC"

# --- report. A finding is ALWAYS logged + printed (never lost to a missing/broken notifier);
#     delivery is attempted through the platform notifier and logged with a DISTINCT outcome. ---
STAMP="$(date -u '+%F %H:%M UTC')"
DUR=$(( $(date +%s) - START ))
SUBJ="[inspector] INTEGRITY ALERT — $(hostname)"

if [ -n "$FINDINGS" ]; then
  MSG="$(printf 'Technical Inspector — integrity anomalies on %s at %s:\n%b' "$SITE" "$STAMP" "$FINDINGS")"
  echo "$MSG" | tee -a "$LOGFILE"                       # finding is retained regardless of delivery
  if [ -n "$NOTIFY_CMD" ] && echo "$MSG" | $NOTIFY_CMD "$SUBJ"; then
    echo "$STAMP inspector: FINDING (${DUR}s) exit=2 — alert delivered" >> "$LOGFILE"
  elif [ -n "$NOTIFY_CMD" ]; then
    echo "$STAMP inspector: FINDING (${DUR}s) exit=2 — !! NOTIFIER FAILED, finding retained above for operator review" >> "$LOGFILE"
  else
    echo "$STAMP inspector: FINDING (${DUR}s) exit=2 — no notifier configured, finding in log above" >> "$LOGFILE"
  fi
  command -v mail >/dev/null 2>&1 && echo "$MSG" | mail -s "$SUBJ" "$ALERT_TO"
  exit 2
fi
echo "$STAMP inspector: clean (${DUR}s) exit=0" >> "$LOGFILE" 2>/dev/null
exit 0
