---
status: ready-for-agent
triage: ready-for-agent
---

# Route Explicit Contract Acceptance Through the Shared Contract Transaction

## Problem Statement

The external wrapper registry (`external_wrapper_contracts.json`) and the system catalog (`system_catalog.json`) must always change together — a system's `wrapper_contract` selector is only meaningful if the contract it names actually exists in the registry. Today there are two independent code paths that write this same pair of files, and only one of them is crash-safe.

`refresh_cli`'s full-system refresh commits a staged registry/catalog pair through `commit_staged_contract_transaction`: it writes a transaction manifest before touching either active file, replaces both through validated temporary artifacts, and validates post-commit hashes. If the process is interrupted after one file has been replaced, `recover_transaction` uses the manifest to finish the same new pair — it never leaves a mixed state.

The explicit, human-reviewed acceptance workflow (`accept_external_wrapper_contract`) writes the same two files through its own bespoke write step: an inline try/except that rolls back whichever file it already wrote if the second write fails, with no transaction manifest and no recovery record. If the process itself is killed between the two writes (not just an exception inside it), there is nothing on disk to recover from — the registry can be updated while the catalog selector still points at nothing, or vice versa. This is the one part of the two write paths where the divergence is a real crash-safety gap, not just a readability difference: an operator using the manual acceptance CLI/API today has a weaker safety guarantee than an operator who only ever runs `refresh_cli`, for no reason grounded in the acceptance workflow's actual requirements.

## Solution

`accept_external_wrapper_contract` keeps everything about *deciding what to write* — proposal validation, registry preparation/versioning, human-selector casefold resolution against the active registry, diff computation for `preview` responses, and cached-scan reclassification preview — exactly as it works today. Only the *write step* changes: when `apply=True` and a write is actually needed, it now commits through `commit_staged_contract_transaction` instead of its own inline write/rollback code, giving the manual acceptance path the same manifest, atomic two-file replacement, and crash recovery story the refresh path already has.

The two entry points remain independent in *when* they trigger — `refresh_cli` auto-detects and stages a contract from complete evidence during a normal refresh; `accept_external_wrapper_contract` is triggered by a human explicitly reviewing and applying a proposal. That trigger independence is unchanged and deliberate (see ADR 0004). What changes is that both now share one *how*: one atomic-commit primitive, one manifest format, one recovery function.

To make this possible without disturbing behavior that already works correctly:

- The transaction manifest gains a `trigger` field (`"refresh"` or `"manual_acceptance"`) so an operator inspecting a manifest after a crash can tell which workflow produced it, without having to infer it from which optional metadata fields happen to be populated.
- `commit_staged_contract_transaction` failures (`ContractTransactionError`) are caught inside `accept_external_wrapper_contract` and re-raised as `ContractAcceptanceError` carrying the same `.code`/`.details`, so existing callers (`service/api.py`'s `/wrapper_contracts/accept` endpoint and `tools/accept_external_wrapper_contract.py`) — which only catch `ContractAcceptanceError` — keep working without modification. The underlying error codes themselves are not remapped: a caller inspecting `.code` now sees the more specific `commit_failed` / `commit_rollback_failed` / `post_commit_validation_failed` instead of today's generic `apply_failed` / `apply_rollback_failed`.
- `accept_external_wrapper_contract`'s response dict gains two new, additive fields: `transaction_id` and `manifest_path`, so an operator can locate and run `recover_transaction` against a manual-acceptance commit exactly as they already can for a refresh-triggered one. No existing field's meaning changes.
- Selector existence validation (does the human-provided `requested_selector` name a contract that actually exists in the active registry) stays inside `contract_acceptance.py`. `commit_staged_contract_transaction` is never given this responsibility — the refresh path never needs it, since it only ever hands the transaction an already-resolved, already-valid selector.
- Preview (`apply=False`) stays entirely inside `contract_acceptance.py` and never calls `commit_staged_contract_transaction`; preview already writes nothing to disk today and gains no new failure modes from this change.

## User Stories

1. As a system maintainer, I want the manual contract-acceptance workflow to commit through the same atomic transaction primitive the refresh workflow uses, so that a crash mid-write during manual review leaves a recoverable manifest instead of a possibly mixed registry/catalog state.
2. As a system maintainer, I want the transaction manifest to record which workflow triggered a commit, so that I can tell a refresh-triggered commit apart from a manually-accepted one when inspecting `.contract_transactions/*.manifest.json` after an interruption.
3. As a system operator, I want an interrupted manual-acceptance commit to be recoverable with the same `recover_transaction` function already used for refresh, so that I don't need a second recovery tool for the same class of failure.
4. As a system maintainer, I want `accept_external_wrapper_contract`'s response to include the transaction id and manifest path for any commit it performs, so that I can find and recover an interrupted commit without reading source code first.
5. As a system maintainer, I want `accept_external_wrapper_contract`'s preview mode (`apply=False`) to remain unchanged — no manifest, no temporary files, no disk writes — so that reviewing a proposal never has a side effect.
6. As a system maintainer, I want selector-existence validation for a human-provided `requested_selector` to continue happening before any commit is attempted, so that a typo'd or nonexistent contract name is rejected with `selector_contract_not_found` exactly as it is today, without that check leaking into the refresh path's transaction primitive.
7. As a developer integrating with `/wrapper_contracts/accept` or the `accept_external_wrapper_contract.py` CLI, I want my existing error handling (catching `ContractAcceptanceError` and reading `.code`) to keep working unchanged, so that this internal refactor requires no changes on my end.
8. As a developer, I want a failed manual-acceptance commit to surface the specific failure reason (`commit_failed`, `commit_rollback_failed`, or `post_commit_validation_failed`) instead of today's generic `apply_failed`/`apply_rollback_failed`, so that I can distinguish "the write itself failed and rolled back cleanly" from "the write failed and rollback also failed" from "the post-write hash check failed" without extra investigation.
9. As a system maintainer, I want the two write paths to stay independent in *when* they run (automatic detection during refresh vs. explicit human review and apply) even after they share the same commit mechanism, so that neither workflow's trigger conditions from ADR 0004 change.

## Implementation Decisions

- The seam for this feature is the existing `accept_external_wrapper_contract` function boundary in `service/contract_acceptance.py` — the same seam every current caller and test already uses. No new module, no new public function, and no new CLI/API surface are introduced.
- Inside `accept_external_wrapper_contract`, the existing per-file `_atomic_write_json` / rollback-on-exception block (used only when `apply=True` and at least one of `registry_diff["changed"]` / `catalog_diff["changed"]` is true) is replaced by a call to `commit_staged_contract_transaction`, passing the already-computed `after_registry` payload as `staged_registry` and the already-resolved, already-validated contract name as `staged_selector` (or `None` when no selector was requested).
- `commit_staged_contract_transaction` gains a `trigger: str` parameter (values `"refresh"` and `"manual_acceptance"`), stored verbatim in the transaction manifest. The existing call site in `analyze_service.refresh_source` passes `"refresh"`; the new call site in `contract_acceptance.accept_external_wrapper_contract` passes `"manual_acceptance"`.
- `accept_external_wrapper_contract` catches `ContractTransactionError` around its call into `commit_staged_contract_transaction` and re-raises `ContractAcceptanceError(exc.code, str(exc), exc.details)` — same code and details, different (existing) exception type — so `service/api.py` and `tools/accept_external_wrapper_contract.py` require no changes.
- `accept_external_wrapper_contract`'s returned dict gains `transaction_id` and `manifest_path` (both empty strings when no commit occurred, e.g. preview mode or a no-op apply where nothing changed), sourced directly from `commit_staged_contract_transaction`'s own return value.
- `commit_staged_contract_transaction`'s existing `"noop"` status (nothing to write) continues to mean nothing is written and no manifest is created; `accept_external_wrapper_contract`'s outward `status` field (`"applied"` / `"preview"`) is unchanged by this — it reflects whether apply was requested, not whether bytes actually changed on disk.
- Selector-existence validation (`_catalog_after_selector`'s casefold lookup against the active registry, raising `selector_contract_not_found`) is untouched and continues to run in `contract_acceptance.py` before the commit call; it is not moved into `contract_transaction.py`, since the refresh path has no equivalent need (it only ever supplies an already-resolved selector).
- `_atomic_write_json` / `_atomic_write_bytes` in `contract_acceptance.py` are removed once no longer called by the write step, unless still used elsewhere in the module (verify before deleting).
- No change to `commit_staged_contract_transaction`'s existing signature/behavior beyond the additive `trigger` parameter — its diff computation (reading current bytes from disk), manifest format, rollback, and `recover_transaction` all stay as-is.
- `CONTEXT.md` and ADR 0004 already record this decision (the `Contract Transaction` glossary term and ADR 0004's "Completion note (2026-08-17)"); no further glossary or ADR work is needed for this spec.

## Testing Decisions

- A good test here asserts externally observable outcomes only: manifest existence/content, `transaction_id`/`manifest_path` in the response, error `.code`, and final file bytes on disk — never internal call sequencing inside `commit_staged_contract_transaction`.
- The two existing rollback-simulation tests in `tests/test_contract_acceptance.py` (`test_apply_failed` around a simulated catalog write failure, and `test_apply_reports_rollback_failure` around a simulated rollback failure) are rewritten to monkeypatch the write primitives `commit_staged_contract_transaction` now calls internally (in `contract_transaction.py`), and to assert the new codes: `commit_failed` and `commit_rollback_failed` respectively (in place of today's `apply_failed` / `apply_rollback_failed`).
- A new focused test asserts that a successful `apply=True` call with a real change writes a manifest whose `trigger` field is `"manual_acceptance"`, using the same tmp_path fixture pattern already used throughout `tests/test_contract_acceptance.py`.
- A new focused test asserts that `accept_external_wrapper_contract`'s response includes a non-empty `transaction_id` and `manifest_path` after a real applied change, and empty values for both in preview mode and in a no-op apply (nothing changed).
- A new focused test simulates a mid-commit interruption during manual acceptance (write registry, crash before catalog write — following the existing pattern already used for `commit_staged_contract_transaction` in `tests/test_contract_transaction.py`, if that file exists, or the refresh-side test that exercises this) and asserts `recover_transaction` against the resulting manifest completes the same pair.
- Existing tests that assert `ContractAcceptanceError` codes for *validation* failures (`invalid_contract_mode`, `selector_contract_not_found`, `incomplete_method_semantics`, etc.) are unaffected — those all happen before any commit attempt and are out of scope for this change.
- No test should assert on `_atomic_write_json`/`_atomic_write_bytes` remaining in `contract_acceptance.py` if they are removed as part of this change — remove or update any test that monkeypatches them directly.

## Out of Scope

- Changing selector-existence validation logic itself, or moving it into `contract_transaction.py`.
- Changing any refresh-path (`refresh_cli`/`analyze_service.refresh_source`) behavior, gating condition, or trigger logic — only the new `trigger` parameter value it passes changes.
- Introducing a preview/dry-run mode inside `commit_staged_contract_transaction` — preview logic stays exactly where it is today, inside `contract_acceptance.py`.
- Any new ADR — ADR 0004 already covers this as a completion note, added during the design discussion that produced this spec.
- Changing `commit_staged_contract_transaction`'s manifest directory default, artifact naming, or hashing/validation scheme.
- Combining registry-only and catalog-only writes into anything other than the existing single-transaction model `commit_staged_contract_transaction` already implements.
- Updating `docs/進階手冊.md` / `docs/流程圖_進階.md` prose ahead of the code change landing — those docs describe current behavior and should be updated in the same change that lands this code, not before.

## Further Notes

This spec was produced from a grilling session (using the domain-modeling skill) over architecture-review candidate #2 ("one seam for the two-file atomic commit"), which flagged this as the one candidate among several where the shallow/duplicated implementation was a live crash-safety gap rather than a readability concern. `CONTEXT.md` gained a `Contract Transaction` glossary term and ADR 0004 gained a "Completion note (2026-08-17)" during that session; both should be treated as already-settled context for whoever implements this spec.
