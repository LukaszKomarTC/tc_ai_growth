#!/usr/bin/env bash
# wp05_finalize.sh — WP-05 closure: seed the six reviewed decisions into the
# tossacycling-production store. Verify-first, idempotent, dormant-safe.
#
# What it does:   pre-verify exact store state -> backup DB -> add 5 origin-marked
#                 policy decisions + the WP-05 completion decision -> post-verify.
# What it NEVER does: run reports, AI tasks, WordPress writes, email, scheduling,
#                 or any network mutation. Read-only except the six decision rows.
#
# Overrides (for tests only): WP05_APP, WP05_SITE, WP05_PY, WP05_USER, WP05_NO_REEXEC.
set -euo pipefail

APP="${WP05_APP:-/opt/tc_ai_growth/app}"
SITE="${WP05_SITE:-tossacycling-production}"
PY="${WP05_PY:-$APP/.venv/bin/python}"
RUN_USER="${WP05_USER:-tcgrowth}"
PROFILE="$APP/orchestrator/profiles/$SITE.env"

fail() { echo "WP-05 BLOCKED: $*" >&2; exit 1; }

# --- run as the service user (root may invoke; we drop to tcgrowth) -------------------
if [ "$(id -un)" != "$RUN_USER" ] && [ -z "${WP05_NO_REEXEC:-}" ]; then
    exec sudo -u "$RUN_USER" \
        WP05_APP="$APP" WP05_SITE="$SITE" WP05_PY="$PY" WP05_USER="$RUN_USER" \
        bash "$0" "$@"
fi

cd "$APP/orchestrator"

# --- profile sanity (grep single keys only — never cat the profile) -------------------
[ -f "$PROFILE" ] || fail "profile not found: $PROFILE"
grep -Eq '^TC_ALLOW_WRITES=false[[:space:]]*$' "$PROFILE" \
    || fail "TC_ALLOW_WRITES=false not set in $PROFILE"

# --- no scheduler may reference this profile ------------------------------------------
if [ -d /etc/systemd/system ]; then
    if grep -rls -- "$SITE" /etc/systemd/system/ 2>/dev/null | grep -q .; then
        fail "a systemd unit references $SITE — production must stay unscheduled"
    fi
fi

# --- state check (queries the store directly; no parsing of human CLI output) ---------
# Prints one word: SEED (2 cases/0 decisions/0 runs, both refs), ALREADY (2/6/0, all six
# titles), or a BLOCKED diagnosis on stderr with exit 3.
state() {
    TC_SITE="$SITE" "$PY" - <<'PYEOF'
import sys
from tc_growth import store

EXPECTED_REFS = {"INC-2026-02-01", "TRK-20260706-050158"}
EXPECTED_TITLES = {
    "Origin D#2 — Serve 410 for verified tobacco/vape spam URL patterns and submit targeted GSC removals",
    "Origin D#4 — Preserve qTranslate XT ES/EN language blocks in the same WordPress post",
    "Origin D#5 — Do not add a manual Tossa Cycling suffix to Yoast SEO titles",
    "Origin D#6 — Apply noindex protection to order-received and order-pay URL patterns",
    "Origin D#7 — Environment-labelled evidence policy for WordPress, GA4 and GSC",
    "tossacycling-production connected as dormant read-only environment",
}

s = store.open_store()
refs = {c.ref for c in s.list_cases(limit=100)}
titles = {d.title for d in s.list_decisions(limit=100)}
runs = len(s.list_runs(limit=100))

if refs == EXPECTED_REFS and not titles and runs == 0:
    print("SEED")
elif refs == EXPECTED_REFS and titles == EXPECTED_TITLES and runs == 0:
    print("ALREADY")
else:
    sys.stderr.write(
        f"unexpected store state: cases={sorted(r or '?' for r in refs)} "
        f"decisions={len(titles)} runs={runs}\n"
        f"missing decisions: {sorted(EXPECTED_TITLES - titles)}\n"
        f"unexpected decisions: {sorted(titles - EXPECTED_TITLES)}\n"
    )
    sys.exit(3)
PYEOF
}

STATE="$(state)" || fail "pre-check found an unexpected store state (see diagnosis above) — nothing was changed"

if [ "$STATE" = "ALREADY" ]; then
    echo "WP-05 ALREADY COMPLETE — 2 cases, 6 decisions, 0 runs; store untouched."
    exit 0
fi
[ "$STATE" = "SEED" ] || fail "unrecognised pre-check result '$STATE' — nothing was changed"

# --- backup the store before writing ---------------------------------------------------
DB="$(grep -E '^TC_DB_PATH=' "$PROFILE" | head -1 | cut -d= -f2- | tr -d '"')"
[ -n "$DB" ] || fail "TC_DB_PATH not set in $PROFILE"
case "$DB" in /*) ;; *) DB="$APP/orchestrator/$DB" ;; esac
[ -f "$DB" ] || fail "store not found at $DB"
BACKUP="$DB.pre-wp05-finalize-$(date +%Y%m%d-%H%M%S)"
cp "$DB" "$BACKUP"
echo "store backup: $BACKUP"

# --- seed the six reviewed decisions (texts fixed 2026-07-13; see WP-05 doc) -----------
add() { "$PY" -m tc_growth.cli --site "$SITE" decision-add "$@" >/dev/null; }

add 'Origin D#2 — Serve 410 for verified tobacco/vape spam URL patterns and submit targeted GSC removals' \
    'Reviewed 2026-07-13. Confirm the affected URL pattern and live serving behavior before implementation. Spam URLs must return 410 and must never redirect to legitimate content. Current state: approved; execution not yet verified. Origin: staging decision D#2; reviewed summary only; no staging run history copied.' \
    'INC-2026-02-01'

add 'Origin D#4 — Preserve qTranslate XT ES/EN language blocks in the same WordPress post' \
    'Reviewed 2026-07-13. Multilingual ES/EN content is stored with [:es]...[:en]...[:] tags in one post. Preserve all tags, update both language blocks in parallel, optimise each language independently, never replace a multilingual field with an untagged single-language value, and do not assume WPML or Polylang separate posts. Origin: staging decision D#4; reviewed summary only; no staging run history copied.'

add 'Origin D#5 — Do not add a manual Tossa Cycling suffix to Yoast SEO titles' \
    'Reviewed 2026-07-13. Yoast appends the configured site title automatically, so drafted SEO titles must not include a duplicate brand suffix such as "| Tossa Cycling". SEO meta descriptions take effect through the controlled connector approval flow. Origin: staging decision D#5; reviewed summary only; no staging run history copied.'

add 'Origin D#6 — Apply noindex protection to order-received and order-pay URL patterns' \
    'Reviewed 2026-07-13. Order confirmation and payment URLs must not be indexed. Confirm production implementation for /pedido/order-received/ and /pedido/order-pay/ patterns. Current state: approved; implementation not yet verified. Origin: staging decision D#6; reviewed summary only; no staging run history copied.' \
    'TRK-20260706-050158'

add 'Origin D#7 — Environment-labelled evidence policy for WordPress, GA4 and GSC' \
    'Reviewed and corrected 2026-07-13 for the multi-environment architecture. Every source must be labelled by property and environment. WordPress connector evidence is valid only for the environment selected by the active profile: tossacycling-staging WordPress data is staging evidence and must never support production revenue claims; tossacycling-production WordPress data is production evidence. GA4 and GSC configured here are production sources. Never combine environments without an explicit comparison. Origin: staging decision D#7; wording corrected during migration; no staging run history copied.'

add 'tossacycling-production connected as dormant read-only environment' \
    'Separate production WordPress user, Application Password, HMAC key and SQLite store are configured. TC_ALLOW_WRITES=false and TC_GROWTH_DISABLE_WRITES=true are independently verified. Authenticated production reads, hostname identity, analytics identities, credential isolation, PII checks, production banner and signed write-route rejection passed. The production profile is dormant and not referenced by any scheduler. Completed 2026-07-13 under WP-05.'

# --- post-verify: must now be exactly ALREADY ------------------------------------------
POST="$(state)" || fail "post-check failed — inspect the store; backup at $BACKUP"
[ "$POST" = "ALREADY" ] || fail "post-check returned '$POST' — inspect the store; backup at $BACKUP"

echo "WP-05 COMPLETE — 2 cases, 6 decisions, 0 runs; production dormant, read-only, unscheduled."
