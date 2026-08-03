# RUNBOOK — TC Operations Console

*The permanent answer to "how do I get to the dashboard?" Owner-facing; no terminal needed for
daily use. Deployment/rollback procedures live in WP-CONSOLE-DEPLOYMENT.md.*

## Access

- **URL:** https://ops.tossacycling.com — bookmark it; works from any computer or phone.
- **Two locks, two credentials** (both in your password manager):
  1. Browser password prompt — user `lukasz` + the "TC Ops basic auth" password (Apache layer).
  2. Console login — the "TC Ops Console token" (the app's own session).
- Sign out: the **Sign out** button (top right). It signs out THIS browser. Because sessions are
  stateless, server-side revocation of a stolen/copied token is **token rotation** (below), not
  logout.
- After a Console **restart** you stay signed in; after a **redeploy** or **token rotation**
  everyone is signed out (by design). The service starts automatically after a server reboot.

## Routine operations

Operations page → **Preview** (read what it will do) → **Execute** → watch the streamed steps;
the `running — Ns` counter next to the buttons proves liveness (an explicit `NO DATA` warning
appears if the stream genuinely stalls). The integrity scan is quiet for ~2 minutes on a clean
run — that's normal; wait for `COMPLETED`. Every run is recorded in the **Evidence** tab
(shared, durable ledger — same one the Monday reports write to).

## Credential rotation

- **Console token** (also = "sign out everywhere"): on the server —
  `sudo sed -i "s|^TC_CONSOLE_TOKEN=.*|TC_CONSOLE_TOKEN=$(openssl rand -hex 24)|" /etc/tc-console.env`
  then `sudo systemctl restart tc-console`, then `sudo cat /etc/tc-console.env` to read the new
  value into your password manager. Never paste it into a chat.
- **Basic-auth password:** `sudo sh -c 'echo "lukasz:$(openssl passwd -apr1)" > /etc/apache2/tc-ops.htpasswd'`
  then `sudo chown root:www-data /etc/apache2/tc-ops.htpasswd && sudo chmod 640 /etc/apache2/tc-ops.htpasswd`.

## Troubleshooting

| Symptom | Meaning | Fix |
|---|---|---|
| Browser password prompt loops | Wrong basic-auth password | Password manager; or rotate it (above) |
| `Internal Server Error` after the password | Apache can't read the htpasswd file | The `chown root:www-data` + `chmod 640` pair above |
| `502` / `Service Unavailable` / page unreachable | Console service down | `systemctl status tc-console` → `sudo systemctl restart tc-console` |
| Signed out unexpectedly | Redeploy or rotation happened, or 12h session expired | Sign in again |
| Operation stuck with `NO DATA for Ns` warning | Stream genuinely lost | Reload the page; check the Evidence tab — the operation itself keeps running and records its result |

## Security model (why it's shaped this way)

TLS everywhere (HTTP 301-redirects to HTTPS) → Apache basic auth → Console token session + CSRF
→ app bound to `127.0.0.1:8385` only (never internet-exposed; Apache is the sole external
path) → operations limited to the accepted registry, executed by an unprivileged user with one
sudoers-allowlisted read-only scan.

**Recorded deviation:** this Plesk runs Apache-only (no nginx), so there is **no request-rate
limit** at the proxy. Compensating controls: two independent auth layers and a strong basic-auth
password. Revisit if exposure grows (fail2ban or mod_security would be the tools).

**Basic auth is transitional** — retirement criteria in WP-CONSOLE-USABILITY.md §U2 (single
Console-native owner login no later than: a second user, U4 daily use, or end-of-package
review).
