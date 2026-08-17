# 02 — Route manual contract acceptance through the shared transaction

**What to build:** An operator applying a reviewed external-wrapper contract proposal through `accept_external_wrapper_contract` (via `/wrapper_contracts/accept` or the CLI) gets the same crash-safety guarantee an operator running `refresh_cli` already gets: a transaction manifest written before either active file is touched, atomic replacement of both files, and recovery to the same new pair if the process is interrupted mid-commit — with no change to any existing caller's error handling or response consumption.

**Blocked by:** 01 — Add `trigger` provenance to the shared contract transaction

**Status:** ready-for-agent

- [ ] `accept_external_wrapper_contract`'s write step (the `apply=True` path, when a real registry and/or catalog change is needed) commits through `commit_staged_contract_transaction` with `trigger="manual_acceptance"`, instead of its own inline write/rollback code.
- [ ] Everything about *deciding what to write* is unchanged: proposal validation, registry preparation/versioning, selector-existence validation against the active registry, diff computation, and cached-scan reclassification preview all behave exactly as before.
- [ ] Preview mode (`apply=False`) still performs no disk writes and never calls `commit_staged_contract_transaction`.
- [ ] A `ContractTransactionError` raised by the commit is caught and re-raised as `ContractAcceptanceError` with the same `.code` and `.details` — the exception type callers already catch is unchanged; only the code values now reflect the more specific `commit_failed` / `commit_rollback_failed` / `post_commit_validation_failed` in place of today's `apply_failed` / `apply_rollback_failed`.
- [ ] `accept_external_wrapper_contract`'s response dict gains `transaction_id` and `manifest_path`, populated after a real commit and empty in preview mode or a no-op apply (nothing changed).
- [ ] `service/api.py`'s `/wrapper_contracts/accept` endpoint and `tools/accept_external_wrapper_contract.py` require no code changes and continue to behave correctly against the new codes and fields.
- [ ] The two existing rollback-simulation tests in `tests/test_contract_acceptance.py` are rewritten to simulate the failure inside the shared transaction's write primitives and assert `commit_failed` / `commit_rollback_failed` respectively.
- [ ] A new test asserts a successful applied change writes a manifest with `trigger="manual_acceptance"`.
- [ ] A new test asserts `transaction_id`/`manifest_path` are non-empty after a real applied change and empty for preview and no-op apply.
- [ ] A new test simulates an interruption mid-commit during manual acceptance and asserts `recover_transaction` against the resulting manifest completes the same registry/catalog pair.
- [ ] Existing validation-failure tests (`invalid_contract_mode`, `selector_contract_not_found`, `incomplete_method_semantics`, etc.) are unaffected, since those all happen before any commit attempt.
- [ ] If `_atomic_write_json`/`_atomic_write_bytes` in `contract_acceptance.py` become unused after this change, they are removed, and any test monkeypatching them directly is updated accordingly.
- [ ] `docs/進階手冊.md` and `docs/流程圖_進階.md` are updated so the description of the two entry points reflects that they remain independent in *when* they trigger but now share one *how* for writing the two files.
