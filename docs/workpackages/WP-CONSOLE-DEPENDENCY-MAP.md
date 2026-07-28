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

## Merge discipline (before anything reaches main)

1. **No bundle merge.** The Console PR must not be the vehicle that merges WP-06, WP-07, the
   Action Registry, and the Inspector in one shot. Each layer earns its own merge.
2. **Independent acceptance per layer.** Each WP passes its own clean-Monday validation and owner
   acceptance on its own terms before it is eligible to merge — see each layer's WP doc.
3. **Merge order, base up:** Action Registry → (Site Intelligence, Source Reader as they pass) →
   Technical Inspector → Operations Console. The Console **rebases onto whatever has actually
   merged**, not onto the development stack.
4. **Registry honesty check at each step:** after each merge, `validate_registry()` passes AND
   every listed operation's backing layer is merged (or the entry is gated). CI already fails a
   registry that contradicts the enforcement layer; extend that to availability at merge time.
5. **Freeze still holds.** Nothing here changes the freeze: these are the *conditions* for the
   restarted gate, not permission to merge now.

## Open decision for the owner

Pick the registry-availability mechanism (flag / split / merge-order) before the Console is
proposed for merge, so the "operations listed == capabilities accepted" invariant is enforced in
code, not just intended here.
