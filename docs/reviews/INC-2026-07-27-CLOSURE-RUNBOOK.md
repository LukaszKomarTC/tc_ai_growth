# INC-2026-07-27 — closure runbook (copy-paste, in order)

Run these on the VPS (owner at the terminal; Claude reads the output). Ordered by re-entry
risk. Each block is safe and read-only unless it says otherwise. Paste output back for grading.
Incident is **not closed** until every PHASE passes and a clean baseline + restore-test + a few
clean monitoring days are done.

## PHASE 1 — persistence audit (highest priority; do first)

```bash
cd /var/www/vhosts/tossacycling.com/httpdocs

# 1a. APPLICATION PASSWORDS — survive password/salt rotation. Enumerate for both admins.
wp user application-password list 1   --allow-root
wp user application-password list 119 --allow-root
#   -> if ANY row you didn't create:  wp user application-password delete <id> --all --allow-root

# 1b. All users with admin capability (must be ONLY ids 1 and 119)
wp user list --role=administrator --fields=ID,user_login,user_email,user_registered --allow-root
```

```bash
# 1c. SSH keys + Linux users + login history (attacker used web-as-lukasz, not SSH — verify no key planted)
for u in /root/.ssh/authorized_keys /home/*/.ssh/authorized_keys /var/www/vhosts/*/.ssh/authorized_keys; do
  echo "== $u =="; cat "$u" 2>/dev/null; done
awk -F: '$3>=1000 && $3<65534 {print $1, $3, $7}' /etc/passwd     # unexpected interactive users?
last -20

# 1d. systemd units/timers created around the breach window (Jul 19+)
systemctl list-timers --all | head -30
find /etc/systemd /lib/systemd -name "*.service" -o -name "*.timer" -newermt "2026-07-18" 2>/dev/null

# 1e. ALL crontabs on the box (we only cleaned lukasz's)
for f in /var/spool/cron/crontabs/*; do echo "== $f =="; cat "$f"; done 2>/dev/null
```

## PHASE 2 — mail: confirm spam actually stopped at the queue

```bash
# queue depth + any pending messages (Postfix); if Plesk uses qmail, use qmail-qstat
mailq 2>/dev/null | tail -5 || postqueue -p 2>/dev/null | tail -5
# recent outbound volume from the site user (spike = still sending)
grep -c "from=<info@tossacycling.com>" /var/log/maillog* 2>/dev/null
grep -c "status=sent" /var/log/maillog* 2>/dev/null | tail
#   -> to purge queued spam if present:  postsuper -d ALL   (DESTRUCTIVE — only if queue is confirmed spam)
```

Then confirm reputation externally: send to a Gmail you own (check Inbox vs Spam) and run the
server IP `212.227.105.0` through https://mxtoolbox.com/blacklists.aspx .

## PHASE 3 — other subscriptions (full treatment, not just a grep)

```bash
# for each site: recent PHP, checksums, kit fingerprint
for D in dashboard.tourdegirona.com tourdegirona.com dev.tourdegirona.com zelcycling.com; do
  echo "############ $D ############"
  R="/var/www/vhosts/$D/httpdocs"
  [ -d "$R" ] || continue
  wp core verify-checksums --path="$R" --allow-root 2>&1 | grep -iE "should not exist|does not match|Success"
  find "$R" -type f -name "*.php" 2>/dev/null | grep -iE "[-_][0-9a-f]{6,8}\.php$"
  find "$R/wp-content/mu-plugins" -name "*.php" 2>/dev/null
  grep -rlE "c080dd89|phpiAgloq|_wp_cuh_restore|_site_transient_health" "$R/wp-content" 2>/dev/null | grep -v duplicator-backups
done
```

## PHASE 4 — orchestrator integrity (shares the box)

```bash
# no shells / tampering under the orchestrator tree; confirm git tree is clean
find /opt/tc_ai_growth -name "*.php" 2>/dev/null            # expect none (it's Python)
grep -rlE "eval\(|base64_decode\(|shell_exec\(|phpiAgloq|c080dd89" /opt/tc_ai_growth/app --include=*.py 2>/dev/null
cd /opt/tc_ai_growth/app && sudo -u tcgrowth git status --porcelain 2>/dev/null | head
```

## PHASE 5 — remaining rotations / hardening not done tonight

- [ ] **Plesk panel** password rotated? (confirm)
- [ ] **Root** password rotated + confirm no attacker SSH key (Phase 1c)
- [ ] Add `define('DISALLOW_FILE_MODS', true);` if you want to hard-block plugin uploads (toggle off when updating), OR rely on Cloudflare + Wordfence-scanner instead
- [ ] Cloudflare edge + rules: block `/wp-json/batch/v1` & `/?rest_route=/batch/v1`; rate-limit `/wp-login.php` & `/xmlrpc.php`; (optional) challenge `/wp-admin`
- [ ] File-integrity/malware detection: weekly checksum-scan cron (below) OR Wordfence-scanner-only
- [ ] Finish 6 premium plugin updates via licensed WP-admin Updates screen

### Weekly checksum-scan cron (lightweight, no plugin) — draft
```bash
# /usr/local/bin/tc-wp-integrity.sh  (emails only on a finding)
#!/bin/bash
cd /var/www/vhosts/tossacycling.com/httpdocs || exit 0
OUT=$(
  wp core verify-checksums --allow-root 2>&1 | grep -iE "should not exist|does not match"
  wp plugin verify-checksums --all --allow-root 2>&1 | grep -iE "should not exist|does not match" | grep -viE "Could not retrieve|Couldn't fetch"
  find wp-content -type f -name "*.php" 2>/dev/null | grep -iE "[-_][0-9a-f]{6,8}\.php$"
  find wp-content/uploads wp-content/mu-plugins -name "*.php" ! -name index.php 2>/dev/null
)
[ -n "$OUT" ] && echo "$OUT" | mail -s "[tossacycling] integrity alert" info@tossacycling.com
# crontab:  17 4 * * 1  /usr/local/bin/tc-wp-integrity.sh
```

## PHASE 6 — formal closure

- [ ] Create a **clean baseline backup** (after Phases 1–4 pass)
- [ ] **Restore-test** it on staging (dev.tourdegirona.com or a scratch subscription)
- [ ] **Monitor** access + file-change logs several clean days, no recurrence
- [ ] Label/hash/lock the 19 GB compromised backup; set deletion date
- [ ] Mark INC-2026-07-27 **CLOSED**; re-baseline the box; lift the Release 0.3 gate suspension
