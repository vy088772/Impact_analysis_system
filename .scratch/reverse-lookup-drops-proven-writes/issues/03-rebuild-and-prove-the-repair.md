# 03 — Rebuild and prove the repair

**What to build:** Proof that the repair works on real data, not only on
fixtures.

Every stored SQL cache is rebuilt, and the deterministic reverse-lookup baseline
in `llamaindex-spec-rag` then finds every required program for all six table
questions, in both routing modes. The six stored-procedure questions lose
nothing they find today.

This is the only acceptance that could have caught the original defect. It lives
in the interaction between graph data and a query gate, so no unit test in
either repository sees it.

**Blocked by:**

- 01 — A referenced object resolves to the node that exists
- 02 — A reverse lookup keeps every fact it has
- `llamaindex-spec-rag` 06 — SELECT_INTO counts as a write on both sides
- `llamaindex-spec-rag` 07 — An unproven path is disclosed, not analysed

**Status:** ready-for-agent

- [ ] The SQL refresh runs for all five declared databases and every cache is
      rebuilt under the new graph version.
- [ ] The deterministic baseline runs with the model disabled, so the result
      depends on no model decision.
- [ ] All six table questions find every required program in mode 4.
- [ ] All six table questions find every required program in mode 5.
- [ ] All six stored-procedure questions find at least what they find today.
- [ ] `table-write-006` passes because its write filter is right, not because
      the filter was skipped.
- [ ] The response size measured on ticket 02 is checked against the ninetieth-
      percentile Answer Latency target, and the measured seconds are recorded
      here.
- [ ] The result set at `context_assembly_concurrency16_candidateset` is not
      used. Five of its six table questions ended in a workflow timeout.
