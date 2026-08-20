# 02 — Detect definition-text drift before slicing

**What to build:** Give SQL-side evidence expansion the same staleness protection the C# side already has (`source_snapshot_hash`). Before slicing any operation's SQL fragment out of its module's `definition` text, the system checks whether that text is still the same length it was when the offset was recorded — if it isn't, evidence expansion fails loudly with `stale_path` instead of silently returning text sliced from the wrong position. This closes the failure mode `01` alone cannot: an operation early enough in a stored procedure that a drifted offset still lands inside the current text's bounds and returns wrong-but-valid-looking content with no error at all.

**Blocked by:** 01 — touches the same graph-node construction code `01` fixes; landing after it keeps the node-schema changes in one coherent order and avoids test fixtures exercising two different bugs at once.

**Status:** ready-for-agent

- [ ] Each `dml_operation`/`unresolved_dynamic_sql` node gains a recorded length of its module's `definition` text at the moment the graph is built.
- [ ] Before any slice is attempted, evidence expansion compares that stored length against the module's current `definition` length as currently loaded; a mismatch raises `PathEvidenceError("stale_path", ...)` with a reason naming the mismatch, and no slice is attempted.
- [ ] A new test extending `tests/test_exact_path_evidence.py`'s `test_path_evidence_rejects_stale_source_snapshot` pattern constructs a fixture where the stored length and the current `definition` length disagree — no real corrupted cache needed, a hand-built mismatch is sufficient — and asserts `PathEvidenceError.code == "stale_path"`.
- [ ] The check does not change behavior for any node whose stored length matches its module's current `definition` length — all existing passing evidence-expansion tests continue to pass unmodified.
