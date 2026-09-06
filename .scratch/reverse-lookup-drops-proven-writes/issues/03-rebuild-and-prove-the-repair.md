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

**Status:** ready-for-agent — mode 4 re-verified and passes. Mode 5 still
needs its own re-run before this ticket can close (see Comments: the first
acceptance attempt was a false negative from a stale cache, now fixed and
corroborated for mode 4 only, at the user's request for this round).

- [x] The SQL refresh runs for all five declared databases and every cache is
      rebuilt under the new graph version. (Substitute method — see Comments.)
- [x] The deterministic baseline runs with the model disabled, so the result
      depends on no model decision.
- [x] All six table questions find every required program in mode 4.
      Confirmed twice: directly via `find_by_table()` (no agent, no model),
      and via a fresh mode-4-only live-agent run. See Comments for the
      `table-write-006` caveat.
- [ ] All six table questions find every required program in mode 5. **Not
      re-run this round** — scoped out at the user's request ("mode 4 就
      好"). The original mode-5 result is the same false negative as mode 4's
      was (same stale-cache mechanism, never re-verified) — do not treat its
      "still misses" reading as current. Needs its own re-run before close.
- [x] All six stored-procedure questions find at least what they find today.
      No `sp-*` question lost a program in mode 4 (re-confirmed this round).
- [x] `table-write-006` passes because its write filter is right, not because
      the filter was skipped. Confirmed at the data layer (`find_by_table`
      shows `productionquoapprove` as `INSERT`+`UPDATE`, both `proven`, for
      `CQM`). Not confirmed live in the mode-4-only run — see Comments, this
      question timed out in the agent loop on all 3 repetitions.
- [x] The response size measured on ticket 02 is checked against the ninetieth-
      percentile Answer Latency target, and the measured seconds are recorded
      here. **Not met — see Comments for the numbers and the newly-observed
      `table-write-006` timeout.**
- [x] The result set at `context_assembly_concurrency16_candidateset` is not
      used. Five of its six table questions ended in a workflow timeout.

## Comments

**Environment constraint (same as ticket 02):** this sandbox has no ODBC
driver (`pyodbc.drivers()` returns `[]`), so `refresh_sql_cli` cannot reach a
live SQL Server. `tools/repair_sql_execution_graphs.py` was used instead — it
rebuilds `sql_execution_graph` from each cache's own already-saved
procedure/view/function definition text via `build_sql_execution_graph()`,
without a database connection. This is the same substitute ticket 02 used for
its own measurement, applied here to all five cache files in place
(`data/sql_cache/*__dbo.json`, excluding `.index.json`/`.meta.json`, which the
tool's glob does not itself exclude — run per-file, not via its CLI, to avoid
feeding it the Object Location Index files). All five confirmed at
`graph_version 4` afterward (PUR: 9,300 nodes / 118,031 relationships; ETON,
Response, STC, SysErrorRecord smaller). The live `service.api:app` process
already running on this machine (port 8800, started before this ticket)
picked up the rebuilt caches automatically — `_is_valid_cache()` checks
`graph_version` before trusting its own in-memory cache, so no restart was
needed.

**The baseline was run for real, three times — the first two were false
negatives.** An earlier, uncommitted attempt
(`llamaindex-spec-rag/evaluation/Impact_analysis/results/table_reverse_lookup_landed/`,
mode 4 only) ran *before* the cache rebuild above — the on-disk PUR cache was
still `graph_version 3` at the time, confirmed by inspecting it directly.
That result is invalid.

A second attempt, run against the rebuilt (`graph_version 4`) caches
(`llamaindex-spec-rag/evaluation/Impact_analysis/results/table_reverse_lookup_after_repair/`,
both modes, 180 observations, using the committed, reviewed
`routing_expectations.candidate.json` — confirmed by content to carry the
spec's actual six tables, Quotation/SOrder/Evaluate/IVWork/VQM/CQM, not the
default expectation file's unrelated set), **still showed the exact same five
missing programs as the pre-repair baseline, byte-for-byte.** This looked at
the time like tickets 01/02's fix not resolving the gate at all. It was wrong.

**Root cause of the false negative: a second, unrelated disk cache never got
invalidated.** `service/analyze_service.py`'s `_rated_invocations_validity_stamp()`
decides whether a *disk-persisted* execution-evidence snapshot
(`data/derived_execution_evidence/*.pkl`, ADR-0017 — cached rated invocations
+ graph + execution paths, reused across requests and across process
restarts) is still fresh by comparing `sql_cache_store.cached_saved_at()`,
which reads `saved_at` out of the paired `.meta.json`. `tools/repair_sql_execution_graphs.py`
rewrites only the main `.json` cache file's `sql_execution_graph` field — it
never touches `.meta.json`, so `saved_at` never changes. Every scope that had
already been evaluated once *before* the offline rebuild kept its stamp
matching, so the disk store kept serving pre-repair execution paths —
complete with the original dangling-node-id defect — regardless of the graph
being correctly rebuilt on disk underneath it. This is exactly why
instrumenting `execution_path_builder.py` directly (temporary `[DEBUG-mgt]`
prints, removed after use) produced nothing: `build_execution_paths()` was
never being called again for these scopes at all.

Fix applied: moved `data/derived_execution_evidence/` aside (backed up under
`/tmp/derived_execution_evidence_backup_*`) and restarted the live
`service.api:app` process so its in-memory retention (`_rated_invocations_retention`,
which is checked *before* the disk store and is just as unaffected by
clearing the directory alone) was also cleared. A direct, non-agentic re-check
via `rag_client.find_by_table()` — no LLM, no agent — then confirmed all six
previously-missing programs resolve as `proven` writes:

| table | program | access_type | evidence_status |
|---|---|---|---|
| Quotation | pilotrequoteissue | INSERT | proven |
| Quotation | productionquoissue | INSERT | proven |
| SOrder | pur_sopublish | UPDATE | proven |
| Evaluate | pilotrequoteissue | INSERT | proven |
| Evaluate | productionquoissue | INSERT | proven |
| IVWork | pur_clearance | UPDATE | proven |
| VQM | productionquoapprove | INSERT, UPDATE | proven |
| CQM | productionquoapprove | UPDATE, INSERT | proven |

**Third run — mode 4 only, corroborating the direct check at the live-agent
level (this round, per the user's request: mode 4 only, `routing_expectations.candidate.json`).**
Fresh directory `llamaindex-spec-rag/evaluation/Impact_analysis/results/table_reverse_lookup_after_repair_mode4/`,
90 observations, run against the now-cleared caches. `missed_target_count`
dropped from 24 (mode 4's prior, false-negative reading) to **3**, and every
one of those 3 is `control-003` / `PUR_SOMaintain.aspx` — a stored-procedure
control question (not one of the six table-write questions, and not one of
the `sp-*` questions checklist item 5 covers), missing identically in the
pre-repair baseline too. **Zero `table-write-*` misses.** All six table
questions find every required program in mode 4.

**`table-write-006` (CQM) timed out on all 3 repetitions this round** (150s
agent timeout, `call_tool` step), so mode 4 never produced a live answer for
it to score. This is not the pre-repair miss recurring — the data layer
confirms the program is now found and proven (table above). It is a new,
separate observation: correctly disclosing CQM's unresolved paths (ticket 02,
`write_only=False` returns 616 raw matches for CQM, `write_only=True` returns
15 proven writes) makes this specific question's tool call slow enough to
sometimes exceed 150s, where the pre-fix (silently-dropping) behavior
happened to finish fast. Checklist item 6 is therefore confirmed at the data
layer but not (yet) at the live-agent layer this round.

**Latency (checklist item 7):** table-write questions alone, this run — n=18,
median 48.1s, p90 150.0s (driven entirely by `table-write-006`'s 3/3
timeouts; the other five questions run 37.9s–57.8s). Over the
ninetieth-percentile-under-30s target in `CONTEXT.md`, consistent with the
system's pre-existing, out-of-scope latency problem already documented in
`evaluation/Impact_analysis/results/mode4_answer_latency_verification.md`
(recorded baseline p90 91s on the full 30-question set). Not attributable to
ticket 02's per-path dedup change specifically (that decision changes
*grouping*, not payload size) — the size driver is decision 3's disclosure of
unresolved paths, which is working as intended; whether that payload size is
itself a latency problem worth a dedicated fix belongs to a separate ticket,
per this spec's own Out of Scope section.

**Follow-up worth its own note (not a new full ticket by itself):**
`tools/repair_sql_execution_graphs.py` should bump `.meta.json`'s `saved_at`
after rewriting a cache's graph (or `_rated_invocations_validity_stamp()`
should key `sql_cache_freshness` on `graph_version`/graph content instead of
purely `saved_at`) — otherwise any future offline graph repair silently fails
to invalidate `derived_execution_evidence_store`, reproducing exactly the
false negative this ticket hit.

**Remaining before this ticket can close:** mode 5 needs its own re-run
against the now-cleared caches (skipped this round at the user's request).
Given mode 4's false negative is now fully explained and reversed, mode 5's
recorded "identical miss" is very likely the same artifact — but that is an
inference, not a re-measurement, and this ticket should not close on an
inference.
