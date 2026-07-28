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
WP="wp --path=$SITE --allow-root"

cd "$SITE" 2>/dev/null || {
  echo "Technical Inspector: docroot missing: $SITE" | mail -s "[inspector] docroot missing" "$ALERT_TO"
  exit 1
}

FINDINGS=""
add(){ FINDINGS="${FINDINGS}\n== $1 ==\n$2\n"; }

# 1. WordPress core integrity (official checksums)
CORE=$($WP core verify-checksums 2>&1 | grep -iE "should not exist|does not match")
[ -n "$CORE" ] && add "CORE checksum anomalies" "$CORE"

# 2. repo-plugin integrity (premium 'not in repo' warnings are expected — filtered out)
PLUG=$($WP plugin verify-checksums --all 2>&1 \
        | grep -iE "does not match|should not exist" \
        | grep -viE "Could not retrieve|Couldn't fetch")
[ -n "$PLUG" ] && add "PLUGIN checksum anomalies" "$PLUG"

# 3. shell-name pattern: hex-suffixed PHP anywhere in wp-content (the kit's signature naming)
HEX=$(find wp-content -type f -name "*.php" 2>/dev/null | grep -iE "[-_][0-9a-f]{6,8}\.php$")
[ -n "$HEX" ] && add "Hex-suffixed PHP (shell naming)" "$HEX"

# 4. executable PHP where none belongs
UPL=$(find wp-content/uploads wp-content/mu-plugins -name "*.php" ! -name index.php 2>/dev/null)
[ -n "$UPL" ] && add "PHP in uploads/mu-plugins" "$UPL"

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

# --- alert only on findings ---
if [ -n "$FINDINGS" ]; then
  printf 'Technical Inspector found integrity anomalies on %s at %s:\n%b\n' \
    "$SITE" "$(date -u '+%Y-%m-%d %H:%M UTC')" "$FINDINGS" \
    | mail -s "[inspector] INTEGRITY ALERT — $(hostname)" "$ALERT_TO"
  exit 2
fi
exit 0
