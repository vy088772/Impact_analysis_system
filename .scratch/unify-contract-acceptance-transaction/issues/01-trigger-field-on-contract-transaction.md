# 01 — Add `trigger` provenance to the shared contract transaction

**What to build:** `commit_staged_contract_transaction` records which workflow triggered a commit, so a manifest found on disk after an interruption is self-describing instead of requiring the reader to infer the trigger from which optional metadata fields happen to be populated.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] `commit_staged_contract_transaction` accepts a `trigger` parameter with allowed values `"refresh"` and `"manual_acceptance"`.
- [ ] The transaction manifest written to disk stores the `trigger` value verbatim.
- [ ] `recover_transaction` is unaffected — it reads and preserves whatever `trigger` value is already in the manifest, without validating or defaulting it itself.
- [ ] The existing call site in `analyze_service.refresh_source` is updated to pass `trigger="refresh"` explicitly.
- [ ] No other behavior of `commit_staged_contract_transaction` changes: diff computation, manifest fields other than `trigger`, atomic replacement order, rollback, and post-commit validation are all unchanged.
- [ ] Existing tests covering `commit_staged_contract_transaction` and the refresh path continue to pass; a focused test asserts the manifest's `trigger` field equals `"refresh"` for a refresh-triggered commit.
