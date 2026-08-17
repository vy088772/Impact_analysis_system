# 04 — Rebuild the STC contract from the current assembly

**What to build:** The system `STC` binds to a contract that covers every public database operation of its wrapper assembly. The call that the analyzer could not resolve now holds the Evidence Status `proven`, and it leaves the review list.

The three previous tickets change how the system builds a contract. They do not change a contract that already exists. A valid Wrapper Contract Selector disables decompilation for the whole refresh, so a bound system never re-examines its assembly. This ticket runs the one manual procedure that rebuilds the contract for `STC`.

This ticket changes stored configuration. Take a backup first.

**Blocked by:** 01, 02, 03 — the rebuild must produce a complete contract under a correct name, so every code change lands first.

**Status:** resolved

- [x] Back up the contract registry and the system catalog before any change.
- [x] Remove the incomplete contract entry for the `SQLFunc` receiver from the registry.
- [x] Clear the Wrapper Contract Selector for `STC` in the system catalog.
- [x] Refresh `STC` once.
- [x] Contract Onboarding creates a contract that holds three `CreateTable` overloads.
- [x] The refresh writes the new selector value back to the system catalog for `STC`.
- [x] The Database Invocation for the two-argument `CreateTable` call holds the Evidence Status `proven`, and it carries a mode and a terminal sink.
- [x] The unresolved evidence count for `STC` drops by one.
- [x] The review candidate count for `STC` drops by one.
- [x] Record the previous and the new contract name, so that a reader can trace the change.

## Answer

Ran the one manual procedure this ticket describes, against the real `STC` checkout and the
real, running-system contract registry and system catalog (not a synthesized fixture).

**Starting state.** The incomplete `sqlfunc` registry entry and the `STC` selector were already
absent/cleared (`config/external_wrapper_contracts.json` held `{"contracts": {}}`; `STC`'s
`wrapper_contract` in `system_catalog.json` was already `""`) — steps 2 and 3 of the procedure had
already landed in an earlier pass. Manual backups were taken anyway
(`.scratch/external-wrapper-surface-completeness/backups/`) before touching anything, per the
ticket's instruction.

**Refresh.** Called `analyze_service.refresh_source({"project": "System Dept 1", "repo": "STC",
"branch": "", "path": ""}, database="STC")` directly — the same function the `/refresh` HTTP
endpoint calls. This did a real `git pull` on the local `STC` clone (fast-forward no-op, already
current), a real local rescan (no live DB needed — SP resolution runs with `analyze_sp=False`),
and reused the cached decompilation of the real `SQLFunc.dll` (cache hit against the Phase-1-fixed
classifier, `attempt_outcome: complete`).

Contract Onboarding created one contract, `sqlfunc`, holding 24 operations including all three
`CreateTable` overloads:

- `CreateTable(string, string)` → `inline_sql` / `Fill` (the previously-missing two-argument
  overload)
- `CreateTable(string, SqlParameter, string)` → `inline_sql` / `Fill`
- `CreateTable(string, SqlParameter[], string)` → `inline_sql` / `Fill`

The refresh wrote `wrapper_contract: "sqlfunc"` back into `system_catalog.json` for `STC`, and
committed both files atomically via the existing contract-transaction mechanism (transaction
`495f33a8421175170f96eb564e74da03`; its own recovery manifest under
`config/.contract_transactions/` holds a second, independent backup of the pre-change registry and
catalog).

**Previous vs. new contract name.** Both the removed incomplete entry and the rebuilt entry are
named `sqlfunc` — the registry held no other entry of that case-folded name at rebuild time, so
`_taken_contract_name` (ticket 03) found nothing to collide with and Contract Onboarding kept the
plain slug rather than appending a fingerprint suffix.

**Effect on `STC`'s observations.** Re-ran the full observation set (40 groups, matching the
Problem Statement's baseline) after the refresh:

- The `CreateTable(string, string)` call site (`STC/CommonFunction.cs`) now reports
  `evidence_status: proven`, `wrapper_contract_mode: inline_sql`, `terminal_sink: Fill`,
  `review_candidate: false` — previously `unresolved` / `overload_not_found`.
- Review candidates: 21 → 20 (drops by exactly one).
- Unresolved evidence: 2 → 1 (drops by exactly one). The one remaining unresolved observation is
  `WriteDB`, an unrelated method — the call-site overload-identification gap that tickets 05/06
  (Phase 2, semantic binding) address, not this ticket's concern.

Validation: read back the committed registry and catalog directly (not just the refresh response)
to confirm the on-disk state independently of the in-memory result.
