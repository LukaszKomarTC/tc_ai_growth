# WP-U4d.2 increment 3 — the on-host Console acceptance run (owner-executed)

*This is the run the agent cannot perform: it needs the VPS, a booted service manager, a real
root-owned runtime, and the owner's browser. Increments 1 and 2 (PR #81) built and proved
everything a machine without those can prove; this document is the rest — the browser-to-root-to-
receipt chain, executed on the host, and the evidence to bring back.*

The owner touches only the browser for the acceptance itself. What needs a terminal is the
**one-time governed setup** — installing the root-owned machinery and turning the operation on —
which is a deliberate, reviewed, human-at-the-console act, not the recurring workflow.

## 0. Preconditions (one-time governed setup, on the VPS)

These establish what `start-acceptance` needs and are done once, by the owner, as root.

1. **A root-owned `current` runtime must exist.** `start-acceptance` runs the acceptance harness
   *as root from root-owned code* — it will refuse (and every launch shows `BLOCKED`) until the
   production deployment machinery has been installed and a runtime materialised. That is the
   normal production install of `tc-deploy-privileged.sh` plus its first `bootstrap`/`apply`; it
   is the same setup PR #80's engine requires.
2. **The receipts directory chain must be root-owned.** `/var/lib/tc-console-acceptance/receipts`
   and every ancestor must be root-owned and not group/other-writable. Root creates it on first
   seal; verify with `stat -c '%n %U:%G %a' /var /var/lib /var/lib/tc-console-acceptance`.
3. **Enable the operation — a reviewed flip.** `deploy_acceptance` ships `enabled=False`. Turning
   it on is a deliberate change to the registry, reviewed like any other, applied to the deployed
   code. Until then the Console shows the Acceptance tab but refuses the launch at both layers.

`deploy_release` stays `enabled=False` throughout: enabling the acceptance does not enable
production deployment.

## 1. Run it from the browser (criteria 1, 6)

1. Open the Console over the SSH tunnel, sign in.
2. **Acceptance** tab → **Run deployment acceptance** → read the preview → **Yes — run the
   acceptance** on the confirmation page. That click is the only input; the browser supplies no
   path, target, service, unit, port or command.
3. Watch the run page stream phases. **Mid-run, restart `tc-console`** (`sudo systemctl restart
   tc-console`), sign back in, reopen the run: it must show the same run with ordered progress
   preserved — proof the record is durable, not in-Console state.

## 2. Read the attested verdict (criteria 2, 3, 7)

A clean run ends **PASS** with zero deferred phases. Confirm the attestation is real, not the
store's opinion:

- `sudo cat /var/lib/tc-console-acceptance/receipts/<run-id>.receipt` — check `engine_head`
  equals the runtime's independently resolved SHA (`sudo cat <snapshot-dir>/current`) and
  `target` is the disposable acceptance target from root-owned config, not production.
- `sudo stat -c '%U:%G %a' /var/lib/tc-console-acceptance/receipts/<run-id>.receipt` — must be
  `root:root 644`.

## 3. Prove the forgeries still fail on the real surface (criterion 8)

On the real store, as `tcgrowth`, attempt each and confirm the run page still reads **BLOCKED**:
forge all phases + a `PASS` verdict column with no receipt; delete/rename the receipt; corrupt a
recorded phase row; point a copied receipt at another run id. None may turn the owner surface
positive.

## 4. Store ownership after the run (criterion 4)

The root side and the Console must operate on the same store with no ownership regression. After
completion and a Console restart, confirm the service account can still open and write the store:
`sudo -u tcgrowth <venv>/bin/python -m tc_growth.cli decisions` (or any store-touching command)
must succeed, and `stat -c '%U:%G' <store.db> <store.db>-*` must show no root-owned db/WAL/journal
artifacts left behind.

## 5. Production untouched, secrets clean (criterion 9)

The run's own report includes the production-untouched check; confirm production paths, service,
store and port are unchanged, and **read the receipt and the streamed phase details by eye** for
secret-bearing output before posting any evidence.

## 6. Bring back

The exact heads of #80 and #81, the real run id, the receipt fields (`engine_head`, `target`,
`verdict`), the restart-reconnection evidence, the store-ownership check, the forgery results, and
the owner-visible final verdict. Both operations stay `enabled=False` and server-refused except
during the reviewed enablement window; merge and any later enablement remain separate owner
decisions.
