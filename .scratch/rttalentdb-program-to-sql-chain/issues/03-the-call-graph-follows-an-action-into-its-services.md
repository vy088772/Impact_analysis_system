# 03 — The call graph follows an action into the services it calls

**Type:** grilling

**Blocked by:** 02

**Status:** needs-triage

**Question:** How does the forward chain (and the backward chain) cross from a
controller action into the service class that the action calls, without
breaking the ADR-0019 scope "a program is one view plus the actions that serve
it"? Decide this in a grilling session after ticket 02 is done, then cut the
implementation tickets.

## Facts (measured 2026-10-06)

- Through the mode 4 seam `rag_client.flow_chain(direction="forward")`, 0 of
  227 RTTalentDB actions reach their stored procedures. 244 of 261 chains
  stop at the action itself. The other 17 reach only a private method of the
  same class (`ReturnResult`). No chain crosses into another class.
- Break 1 — file scope: `build_forward_chain`
  (`service/flow_chain_builder.py:174`) builds the adjacency only from the
  files that pass `owns_file`. For an MVC program those are the view and the
  controller, so `Services/MS/JobTypeService.cs` is never in the graph.
- Break 2 — name match: `_method_adjacency`
  (`service/flow_chain_builder.py:73`) links a call only when the call text is
  a bare method name in the set. The scan records the call as
  `'_service.InvalidateJobType'`, so it never matches, even inside the owned
  files.
- Break 3 — receiver type: `_service` is a primary constructor parameter of
  interface type `IJobTypeService`. The chain needs the interface resolved to
  `JobTypeService`. Ticket 01 handles the primary constructor for the wrapper
  receiver only.
- Execution paths join the chain by `entry_method` in `reachable_methods`
  (`flow_chain_builder.py:199`). The entry method of a path is the service
  method (`InvalidateJobType`), so a path joins only when the chain reaches it.
- The SQL side is complete: 162 of the 163 called procedures have every table
  of their text in the SQL Execution Graph. The one gap is dynamic SQL in
  `usp_RPT_SkillClassificationPersonnelDetailQry` (Unresolved Dynamic SQL, by
  design).

## Questions for the grilling session

1. **Scope.** ADR-0019 decides which *actions* belong to a program. Does it
   also limit which *callees* the chain follows? If the chain follows callees
   outside the owned files, is that a new ADR or an amendment to ADR-0019?
2. **Noise.** ADR-0019 consequences warn that a shared controller pushed into
   every screen "is noise, not an answer". Many controllers share one
   service. If the chain follows only the service *methods* that the action
   calls (not the whole class), does that stay inside the warning?
3. **Interface to implementation.** Reuse the Local Implementer rule of
   `.scratch/wrapper-receiver-resolves-through-interface/` (one local
   implementer resolves, two or more report as ambiguous)? Or a new rule for
   the call graph?
4. **Where the receiver type comes from.** The regex parser records
   `'_service.InvalidateJobType'` with no type. Resolve the type in Python
   from the class fields and primary constructor, or let the Roslyn host
   (semantic model) record the bound target of each call?
5. **Depth and cycles.** How deep does the chain follow (service → service →
   helper)? `_reachable_from` has a `max_depth` for the main path only.
6. **Existing precedent.** `/analyze` already follows calls into other files
   through `expand_related_programs` (`service/analyze_service.py:1875`, on
   `expand_depth > 0`). For JobType it returned `related_programs: []`. Is
   that the same gap (bare-name match), and should the forward chain and that
   expansion share one rule?
7. **Backward direction.** The backward chain builds a reverse adjacency per
   file (`_rev_adj_for_file`) and finds UI anchors through
   `scan.aspx_results` only. For an MVC system, does a table reach the
   controller action and the view, or does it stop at the service method?
8. **Acceptance.** Which number closes the work: all 227 actions fully
   matched by `compare_flow.py`, or a stated lower bound with each miss
   explained (for example the 16 procedures reached only through a helper
   parameter, ADR-0020)?

## Feedback loop

```
cd llamaindex-spec-rag
python3 ../Impact_analysis_system/.scratch/rttalentdb-program-to-sql-chain/probes/truth.py \
    ../Impact_analysis_system/data/repos/System_Dept_1/RTTalentDB/RTTalentDB \
    ../Impact_analysis_system/.scratch/rttalentdb-program-to-sql-chain/probes/truth.json
PYTHONPATH=. .venv/bin/python ../Impact_analysis_system/.scratch/rttalentdb-program-to-sql-chain/probes/compare_flow.py flow_after.json
```

Baseline (`probes/flow_baseline.json`):

```
actions that should reach SP 227 | fully matched 0 | partial 0 | none 227
reachable_methods == 1 (stops at action): 244 of 261
SP coverage 0 / 163
```

`truth.py` is a probe, not an oracle. It resolves `recv.Method(` through the
class fields and primary constructor, and an interface to every class that
implements it. It follows a helper parameter only one call deep. Check a
surprising mismatch against the source before you trust either side.

## Answer

(Fill in after the grilling session.)
