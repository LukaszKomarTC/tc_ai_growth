# WP-U4d.2 increment 3 — the on-host Console acceptance run (owner-executed)

*Increments 1–2 (PR #81) built the owner surface and made a positive verdict unforgeable by the
application layer. This is the on-host run the agent cannot perform — it needs the VPS, a booted
service manager, a real root-owned runtime, and the owner's browser.*

The correction from the previous review is applied here: **the acceptance verification is not
terminal work.** The runner performs the adversarial and integration checks itself — the forgery
battery against a disposable record, the receipt binding, the store-ownership check, the
Console-restart reconnection — and records each as durable evidence. The owner approves once in
the browser and reads one verdict. What still needs a terminal is only the **one-time governed
setup**.

## 0. One-time governed setup (terminal, once, by the owner)

1. **A root-owned `current` runtime must exist.** `start-acceptance` runs the acceptance harness
   as root *from root-owned code*; it refuses (every launch shows `BLOCKED`) until the production
   deployment machinery is installed and a runtime materialised — the same install PR #80's
   engine requires (`install-tc-deploy.sh`, then the first `bootstrap`/`apply`).
2. **Enable the operation — a reviewed flip.** `deploy_acceptance` ships `enabled=False`. Turning
   it on is a deliberate registry change, reviewed like any other, applied to the deployed code.
   `deploy_release` stays `enabled=False`: enabling the acceptance does not enable production
   deployment.

The receipts directory (`/var/lib/tc-console-acceptance/receipts`) is created and locked down by
root on first seal; no manual step is needed.

## 1. Run it — browser only (all ten criteria, exercised by the runner)

1. Open the Console over the SSH tunnel, sign in.
2. **Acceptance** tab → **Run deployment acceptance** → read the preview → confirm. That click is
   the only input; the browser supplies no path, target, service, unit, port or command
   (criteria 1, 2).
3. The run streams phases and then the runner's own self-checks, each recorded as evidence:
   - the engine acceptance (deploy, injected failure, rollback, production-untouched) with the
     six systemd phases executing on the booted host (criterion 6, and 7's clean/failure paths);
   - **`check-attestation-resistance`** — the forgery battery (forged rows + PASS column, wrong
     run id, digest mismatch, non-root receipt) run against a *disposable* record, proving each
     yields `BLOCKED` on this host, without anyone editing the live store (criterion 5, 8);
   - **`check-receipt-binds-runtime-and-target`** — root confirms the receipt binds the
     independently-resolved runtime SHA and a disposable, non-production target (criterion 4);
   - **`check-store-ownership-preserved`** — no root-owned db/WAL/journal is left behind and the
     service account can reopen and write the store (criterion 4's store property, 6);
   - **`check-console-restart-reconnect`** — the runner restarts `tc-console` and confirms the
     durable run record survived, so the owner sees reconnection proven, not performed by hand
     (criterion 3).
4. Read the single verdict at the top of the run page: `PASS`, `FAILED SAFELY`, or `BLOCKED`
   (criterion 8). A clean run is `PASS` with zero deferred phases; a controlled failure is
   `FAILED SAFELY` only when rollback and production-state evidence are complete, else `BLOCKED`.
   The verdict is computed against the root-owned receipt — the store's own column is never
   trusted.

## 2. Evidence to bring back

The run page and the receipt already carry everything; capture it from the browser (and, for the
receipt, one `sudo cat` if you want the raw file for the record):

- the exact heads of #80 and #81, the run id, and the owner-visible final verdict;
- the recorded status of each self-check phase (all `ok` for a `PASS`);
- the receipt fields (`engine_head`, `target`, `verdict`) as shown, for the on-host cross-check;
- confirmation the production-untouched phase is green.

**Read the streamed phase details by eye** for secret-bearing output before posting; the Console
redacts stored detail, but the human review still applies (criterion 7, 9).

Both operations stay `enabled=False` and server-refused except during the reviewed enablement
window; merge and any later enablement remain separate owner decisions (criterion 9, 10).
