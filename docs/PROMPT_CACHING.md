# Prompt caching — activation record + post-gate verification protocol

**Status:** code-complete on `feature/prompt-caching` (43a86ea), reviewed and accepted
2026-07-20. Merges and deploys ONLY after the Release 0.3 gate closes (Monday 2026-07-27
sequence). Recorded now so the corrected verification criteria survive to deployment day.

## What is active

Every `messages.create` call in `AnthropicRuntime` sends top-level automatic caching:

```python
cache_control={"type": "ephemeral", "ttl": "1h"}
```

The API places the cache breakpoint at the last cacheable block itself; no manual
breakpoints, no prompt restructuring. Manual breakpoints are introduced only if the ledger
later proves automatic caching leaves significant reusable context uncached.

Cache usage is captured per run into `runs.detail` as JSON (additive, no schema change):

```json
{"cache_creation_tokens": 4096, "cache_read_tokens": 0}
```

`detail` stays NULL for runtimes that don't report caching — no fake zeros.

## Post-gate deployment steps (in order)

1. Merge `feature/prompt-caching` (after the 0.3 close-out sequence completes).
2. Deploy staging; **verify the running venv actually received the SDK floor bump**
   (`anthropic>=0.117` — older SDKs reject the kwarg with `TypeError`):

   ```bash
   /opt/tc_ai_growth/app/.venv/bin/python -c 'import anthropic; print(anthropic.__version__)'
   ```

   A successful install in the repo environment does not prove the service process picked
   it up — restart the runtime and confirm the service uses that same venv.
3. Run the same representative workflow twice within one hour.
4. Grade against the success criteria below.
5. Leave enabled for scheduled runs; counters feed the future AI FinOps dashboard.

## Success criteria (pre-registered — the checklist decides)

- Run 1: `cache_creation_tokens > 0`
- Run 2 (equivalent, within the 1h TTL): `cache_read_tokens > 0`
- Financial: run 2's effective input cost < run 1's (compare the pair; see cost caveats)

**Explicitly NOT required:** `cache_creation_tokens == 0` on run 2. The agent loop appends
assistant messages and tool results each iteration, so a run can both read the stable prefix
AND create new extended cache entries. Counters are summed across the whole loop; inspect
the totals, not one final response. Tool definitions participate in the cached prefix —
changing the tool set invalidates reuse (registration order is deterministic today; keep it
that way).

If BOTH counters are zero: first suspect the model-dependent minimum cacheable prefix
(~1024–4096 tokens depending on tier — shorter prefixes silently don't cache), not a bug.

## Ledger query (field names match the code — verified against report.py)

SQLite, against `orchestrator/data/*.db`:

```sql
SELECT id, started_at, model, prompt_tokens, completion_tokens,
       json_extract(detail, '$.cache_creation_tokens') AS cache_created,
       json_extract(detail, '$.cache_read_tokens')     AS cache_read,
       cost_usd
FROM runs ORDER BY started_at DESC LIMIT 10;
```

(Earlier drafts of this query used `$.cache_creation_input_tokens` and a `cost` column —
those names don't exist in this schema.)

## Known cost-accounting limitation (accepted, not yet fixed)

`core/cost.py::estimate_cost` prices only `prompt_tokens` + `completion_tokens`. With
caching active, Anthropic's `usage.input_tokens` EXCLUDES cache-creation and cache-read
tokens, which are billed separately (creation at a premium — 2× for 1h TTL; reads at ~0.1×).
Consequences:

- `cost_usd` will under-report true spend on cached runs — do NOT use it for the
  before/after comparison; use the counters and list pricing directly.
- The first cached run may cost slightly MORE than an uncached run (creation premium);
  savings appear on reuse. Compare pairs or several repeats, never run 1 vs the
  historical average.

Fix (extend `estimate_cost` with cache-aware rates) is a small post-gate follow-up,
candidate for the AI FinOps dashboard work.
