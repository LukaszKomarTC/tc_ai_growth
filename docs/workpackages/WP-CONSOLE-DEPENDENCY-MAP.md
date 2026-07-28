# Operations Console — branch dependency map & merge discipline

**Why this doc exists.** The `feature/operations-console` branch, as built, sits on top of a
stack of other feature layers (they were merged/stacked in during the freeze so the Console could
be built against them). That is fine *for development*, but it creates a real governance hazard:
**merging the Console must not become a backdoor merge of several frozen branches.** This map
names every layer, what the Console actually depends on versus what is merely co-present, and the
discipline that must hold before anything reaches `main`.

Frozen base: `main` @ `527fdea`. Everything below is unmerged and waits for the restarted
clean-Monday gate.

## Layers present on the branch (since `527fdea`)

| Layer | WP | Modules | Console depends on it? | Independent acceptance |
|---|---|---|---|---|
| Site Intelligence | WP-06 | `core/site_intel.py`, `core/lifecycle.py`, `tools/site_intel.py` | **No** (only via registry catalogue entries `refresh_site_snapshot`, `query_site_map`) | code-complete on branch; VPS/owner acceptance PENDING |
| Source Reader | WP-07 | `core/source_reader.py`, `tools/source_reader.py` | **No** (only via registry entries `read_source_file`, `list_source_dir`) | code-complete on branch; VPS/owner acceptance PENDING |
| Drafting rule (SEO title vs H1) | WP-09 (early) | prompt/rule text | No | rule adopted; validated in report tests |
| **Action Registry** | — | `core/actions.py` | **YES — hard dependency** | validated in CI (`test_action_registry`); owner acceptance PENDING |
| Technical Inspector v0 | — | `scripts/wp-integrity-scan.sh` | **YES for op #2** (invoked by `run_integrity_scan`) | detection validated; cron + alert-delivery acceptance PENDING |
| Operations Console | this WP | `core/executor.py`, `console.py` | — | slice-1 mechanism built + tested; VPS/owner acceptance PENDING |

Also relies on modules already on `main`: `core/approval.py` (phase gate), the tool registry,
the store, config. Those are not part of this stack.

## True vs. co-present dependencies

- **Hard runtime dependency:** `console.py` → `core/executor.py` → `core/actions.py`
  (Action Registry) → `core/approval.py` (on main). The Console cannot function without the
  Action Registry; that is a genuine dependency and they must ship together.
- **Op-specific dependency:** `run_integrity_scan` needs the Technical Inspector script deployed;
  the SMTP op needs only the existing mail config. Each *operation* has its own backing
  requirement — an operation must not be surfaced as runnable unless its backing layer is present.
- **Co-present, NOT depended on:** Site Intelligence and Source Reader are on the branch because
  the Action Registry *catalogues* their operations. The executor only touches those layers if
  someone executes those specific ops. So the Console does not need WP-06/WP-07 code to run — it
  needs the registry to **not advertise operations whose backing layer isn't merged.**

## The registry must never advertise an unavailable operation

This is the linchpin that lets the Console merge without dragging WP-06/WP-07 with it: the Action
Registry is the contract, so an operation is listed **only if its backing capability is actually
merged and accepted.** Enforcement options (decide at merge time, don't leave implicit):

- gate registry entries by an `enabled`/availability flag tied to what's merged, or
- split the registry so WP-06/WP-07 operations are contributed by their own layers, or
- merge the backing layers first, so the entries are honest by the time the Console lands.

Whichever we pick, the invariant is: **the operations a user can click == the capabilities that
have passed their own acceptance.** A registry that lists an op whose layer is frozen is a lie,
and the Console would surface it.

## The actual import DAG (evidence, not narrative)

Measured from the source, the Console's **static import closure** is small and clean:

```
console.py → core/executor.py → core/actions.py → core/approval.py     (+ stdlib only)
```

None of these import Site Intelligence or Source Reader at module load. Verified:
`core/actions.py` imports **only** `core/approval.py`; it references WP-06/WP-07 tools **by name,
as data**, never importing them. The feature implementations enter only through
`tools/load.py` — imported **lazily**, inside `executor._run_tool`, *and only when a tool-bound
op is actually executed* — plus one registry **test** that asserts those tool names are
registered.

So the earlier claim "the registry needs those layers to describe itself" was **too strong** and
is retracted. The coupling is **data + test + lazy-dispatch**, not imports. Consequence: a
minimal Console (baseline + registry + gate + Inspector op) is import-clean; what blocks a clean
extraction is (a) the WP-06/WP-07 **registry entries**, (b) their **`TOOL_MIN_PHASE`** entries in
the gate, and (c) the **registration test**.

## Architectural debt (record, do not fix under deployment pressure)

> **The Action Registry couples capability *description* to implementation *availability*.** A
> control-plane registry should be able to declare an operation as `registered / implementation
> unavailable / acceptance pending / execution disabled` **without importing (or requiring) the
> unaccepted feature implementation.** Today it cannot cleanly, so every future control-plane
> feature risks inheriting the whole feature stack. Future registry versions should decouple
> declaration from availability (a status field + a separate implementation-discovery step). This
> is design debt, not a blocker for VPS acceptance — but it must not be quietly promoted into a
> permanent architectural principle.

## Merge discipline — needs the real DAG, not a preferred order

Before merge we produce the actual **import + test dependency graph** and pick between:

- **Scenario A — implementation layers first:** Site Intelligence → Source Reader → shared
  gate/lifecycle changes → Action Registry → Technical Inspector → Console. Correct *if* we keep
  the registry as-is (it declares WP-06/WP-07 ops, so those must exist first).
- **Scenario B — decoupled registry first:** a minimal registry schema + validation → feature
  layers → per-layer operation registration → Inspector → Console. Architecturally cleaner
  (pays down the debt above), but needs the decoupling refactor. The import DAG shows this is
  *viable*, not blocked.

Do **not** assert "base-up" as if it were settled: whether the Action Registry is independently
mergeable *before* WP-06/WP-07 depends entirely on whether we do the Scenario-B decoupling. That
choice is made at merge time, on the evidence, not now.

Fixed regardless of scenario:
1. **No bundle merge** — the Console PR is never the vehicle that merges WP-06/WP-07 + registry +
   Inspector in one shot.
2. **Independent acceptance per layer** before it is eligible to merge.
3. **Registry honesty invariant:** the operations a user can click **==** the capabilities that
   passed their own acceptance. `validate_registry()` must pass AND every listed op's backing
   layer is merged or its entry is gated. (This is what the debt item, once paid, enforces in code.)
4. **Freeze still holds** — these are the conditions for the restarted gate, not permission now.

## Branch decision (current operating decision)

**Keep the current stacked branch for development and VPS acceptance. Do NOT reconstruct now**
(it would delay the real milestone and risk another divergent implementation). **Do NOT formally
approve the current stack as the permanent merge model.** Before merge: produce the real
dependency DAG and decide Scenario A vs B — and do not merge the Console until the Action Registry
can be shown **not** to pull unaccepted capabilities into `main`.
