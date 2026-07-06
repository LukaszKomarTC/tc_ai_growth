# Weekly report — systemd timer (self-hosted VPS runtime)

Schedules the Monday growth digest on the VPS. This is the self-hosted alternative to the
Managed Agents scheduled deployment in `../weekly_report.yaml`; use whichever runtime you run.

The job runs as a dedicated **non-root** system user (`tcgrowth`), reads its config from
`orchestrator/.env`, and delivers by email. It writes nothing to disk (yet), so the unit keeps
the filesystem read-only for defense in depth.

## One-time setup (run as root)

```bash
# 1. Dedicated, loginless system user; own the app tree with it.
useradd --system --home-dir /opt/tc_ai_growth/app --shell /usr/sbin/nologin tcgrowth
chown -R tcgrowth:tcgrowth /opt/tc_ai_growth/app
chmod 600 /opt/tc_ai_growth/app/orchestrator/.env          # secrets: owner-only
# If Google service-account creds are used:
# chmod 600 /opt/tc_ai_growth/app/orchestrator/secrets/*.json

# Persistence store: create the writable data dir (the unit keeps everything else read-only)
# and seed Case #1 (the Merchant Center incident).
mkdir -p /opt/tc_ai_growth/app/orchestrator/data
chown tcgrowth:tcgrowth /opt/tc_ai_growth/app/orchestrator/data
sudo -u tcgrowth /opt/tc_ai_growth/app/.venv/bin/python -m tc_growth.cli db-init

# 2. Install the units.
cp /opt/tc_ai_growth/app/orchestrator/deployments/systemd/tc-weekly-report.service /etc/systemd/system/
cp /opt/tc_ai_growth/app/orchestrator/deployments/systemd/tc-weekly-report.timer   /etc/systemd/system/
systemctl daemon-reload

# 3. Enable the timer (starts counting to next Monday).
systemctl enable --now tc-weekly-report.timer
```

## Verify

```bash
systemctl list-timers tc-weekly-report.timer      # shows the NEXT firing time
# One real run now (generates + emails a report; costs AI tokens):
systemctl start tc-weekly-report.service
journalctl -u tc-weekly-report.service --no-pager  # see stdout/stderr of that run
```

A green run emails the digest to `TC_REPORT_RECIPIENT`. Tools without credentials yet (Google
Ads, Meta, etc.) are reported under "Pending integrations" — they don't fail the run.

## Kill switch

```bash
systemctl disable --now tc-weekly-report.timer     # stop all future runs
```

Revoking the API key / SMTP password in the provider consoles is the credential-level kill switch.

---

# Dashboard — always-on service + Plesk-fronted access

The dashboard itself binds **127.0.0.1:8383 only** and serves GET requests exclusively; the public
face is a Plesk-managed subdomain (TLS via Let's Encrypt + HTTP basic auth) that reverse-proxies to
that loopback port. Compromising the password exposes a read-only view, nothing more.

## 1. Install the service (as root)

```bash
cp /opt/tc_ai_growth/app/orchestrator/deployments/systemd/tc-dashboard.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tc-dashboard.service
systemctl status tc-dashboard.service --no-pager   # expect: active (running)
```

## 2. Create the password file (as root)

```bash
apt-get install -y apache2-utils
htpasswd -c /etc/nginx/tcgrowth.htpasswd <your-username>     # prompts for the password, hidden
chmod 640 /etc/nginx/tcgrowth.htpasswd && chgrp nginx /etc/nginx/tcgrowth.htpasswd
```

## 3. Plesk (clicks)

1. **Websites & Domains → Add Subdomain** — name `dashboard`, under `tourdegirona.com`.
2. On the new subdomain: **SSL/TLS Certificates → Install** a free Let's Encrypt certificate
   (tick "Secure the subdomain").
3. **Apache & nginx Settings → Additional nginx directives**, paste:

   ```nginx
   location / {
       auth_basic "TC Growth";
       auth_basic_user_file /etc/nginx/tcgrowth.htpasswd;
       proxy_pass http://127.0.0.1:8383;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```

4. Apply. Open `https://dashboard.tourdegirona.com`, enter the username/password → dashboard.

## 3-alt. Plesk WITHOUT nginx directives (Apache-only setups)

If "Apache & nginx Settings" shows no "Additional nginx directives" box, the Plesk nginx
reverse-proxy component is disabled and Apache serves directly. Use the Apache equivalent
(functionally identical; survives Plesk reloads because it lives in Plesk's per-vhost config):

```bash
# Password file readable by Apache (www-data), and the proxy modules:
htpasswd -c /etc/apache2/tcgrowth.htpasswd <your-username>
chown root:www-data /etc/apache2/tcgrowth.htpasswd && chmod 640 /etc/apache2/tcgrowth.htpasswd
a2enmod proxy proxy_http headers && systemctl restart apache2
```

Then paste into **Additional Apache directives for HTTPS** (leave the HTTP box empty; the
301-to-HTTPS redirect covers it):

```apache
ProxyRequests Off
ProxyPreserveHost On

<Location "/">
    AuthType Basic
    AuthName "TC Growth"
    AuthUserFile /etc/apache2/tcgrowth.htpasswd
    Require valid-user
</Location>

ProxyPass / http://127.0.0.1:8383/
ProxyPassReverse / http://127.0.0.1:8383/

Header always set X-Robots-Tag "noindex, nofollow"
```

Do NOT flip the whole server to nginx (`plesk sbin nginxmng --enable`) just for this — that
changes the serving stack of every site on the box to solve a one-vhost problem.

---

# Auto-deploy — pull-based GitOps (no shell access for anyone)

Merges to `main` deploy themselves: every 5 minutes the timer checks `origin/main`; on new
commits it pulls, reinstalls, runs the FULL test suite, and only then restarts the dashboard.
**If tests fail it rolls back to the previous commit** — the box never serves a broken main.
Log: `orchestrator/data/autodeploy.log`.

## One-time setup (as root)

```bash
# 1. The single privilege the deploy user needs: restarting the dashboard. Nothing else.
cat > /etc/sudoers.d/tcgrowth-deploy <<'SUDO'
tcgrowth ALL=(root) NOPASSWD: /usr/bin/systemctl restart tc-dashboard.service
SUDO
chmod 440 /etc/sudoers.d/tcgrowth-deploy

# 2. Install the units.
chmod +x /opt/tc_ai_growth/app/orchestrator/scripts/autodeploy.sh
cp /opt/tc_ai_growth/app/orchestrator/deployments/systemd/tc-autodeploy.service /etc/systemd/system/
cp /opt/tc_ai_growth/app/orchestrator/deployments/systemd/tc-autodeploy.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tc-autodeploy.timer

# 3. Verify (fires within 2 min of boot / 5 min cycle):
systemctl list-timers tc-autodeploy.timer
tail -f /opt/tc_ai_growth/app/orchestrator/data/autodeploy.log
```

Requirements: the repo remote must be pullable by the `tcgrowth` user (public repo or
credentials readable by tcgrowth). Kill switch: `systemctl disable --now tc-autodeploy.timer`.

## Notes

- **Hosting Settings** for the subdomain: enable "Permanent SEO-safe 301 redirect from HTTP to HTTPS"
  so the password never travels over plain HTTP.
- The subdomain serves a read-only console; there is nothing to index — the noindex header is
  included in both variants above.
- Kill switch: `systemctl disable --now tc-dashboard.service` (the subdomain then returns 502).
