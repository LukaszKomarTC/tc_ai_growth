#!/usr/bin/env bash
# Read-only smoke test. Invokes ONLY read tools via the CLI's single-tool `smoke` path (no AI
# runtime, no drafts, no writes). Safe to run against staging — it cannot mutate anything.
#
# Usage (from orchestrator/, with .env configured and the venv active):
#   ./scripts/smoke.sh
#
# Each tool prints a structured result or a clear error (missing credential / wrong scope), and a
# missing credential is reported, not fatal — so you can fix issues one at a time.

set -u
CLI="python -m tc_growth.cli"
base="${TC_WP_BASE_URL:-https://example.com}"

echo "== available tools =="
$CLI list-tools

run() {
  echo
  echo "== smoke: $1 =="
  $CLI smoke "$1" "$2" || true   # non-zero just means that tool needs config; keep going
}

run gsc_search_analytics   '{"start_date":"28daysAgo","end_date":"today","dimensions":["query"],"row_limit":5}'
run ga4_report             '{"start_date":"28daysAgo","end_date":"today"}'
run woo_revenue_attribution '{"days":28}'
run pagespeed_check        "{\"url\":\"${base%/}/\"}"
run wp_list                '{"kind":"rentals"}'

echo
echo "== read-only smoke complete (no writes were possible) =="
