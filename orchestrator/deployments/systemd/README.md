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
