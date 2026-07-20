# WP-07 — Read-only Source Reader (plugins/themes/logs, both properties)

**Status:** SPEC 2026-07-20 — owner decision: production read layer brought forward. Build
order: after WP-06 slices 1–2. Code on `feature/site-intelligence` family branches; merges
after Release 0.3 signs off.

**Why:** the 2026-07-19/20 diagnosis (qTranslate REST filtering × Yoast indexables) required
reading plugin source the agent could not reach — only OUR plugin (in the repo) was readable;
qTranslate's and Yoast's actual code had to be inferred from symptoms across ~10 human relay
rounds. A scoped source read answers such questions in one tool call.

## Design

Local filesystem tool (`source_read`, `source_list`) — the orchestrator is co-located with
both sites on the VPS, so NO FTP, no network credentials, no new daemon.

**Path allowlist (per profile, resolved roots):**
- `<site>/wp-content/plugins/`
- `<site>/wp-content/themes/`
- `<site>/wp-content/mu-plugins/`
- selected log locations (Plesk `logs/` for the vhost; PHP error log)

**Deny-list (checked AFTER realpath canonicalization — symlink escapes die here):**
- `wp-config.php` anywhere, `.env*`, `*.sql`, `*.zip/tar/gz` (backup archives)
- anything under `uploads/` (media + potential exports), key/credential files (`*.pem`,
  `*.key`, `auth`-named files)

**Controls:** read-only file opens; per-read size cap (256 KB, truncate with marker);
per-run read budget; every read audit-logged (profile, path, bytes, run id); phase
READ_ONLY; production profile served by the same tool — reads are ordinary capability
(VISION), no amendment required.

**Owner setup (one-time):** grant the `tcgrowth` user group/ACL read on the two
`wp-content` trees (`setfacl -R -m g:tcgrowth:rX …/wp-content/{plugins,themes,mu-plugins}`)
— no write bit anywhere.

## Acceptance

- [ ] Path-traversal and symlink-escape attempts rejected (tests with fixtures).
- [ ] Deny-list wins over allowlist in every test (wp-config, .env, backups unreachable).
- [ ] Reads audit-logged; size caps enforced; suite green.
- [ ] Live proof: agent reads qTranslate XT's postmeta filter on staging and cites
      file+line for the behaviour we established empirically on 2026-07-20.
