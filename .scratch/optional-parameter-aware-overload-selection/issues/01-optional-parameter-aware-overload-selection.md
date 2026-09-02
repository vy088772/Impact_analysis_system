# 01 — Overload selection reads Required Parameter Count and Mode Argument Carriage

**What to build:** A call to an external wrapper method binds to the overload C#
itself would bind it to, when the difference between the candidates is a trailing
optional parameter. Today the gateway compares argument count to `method_arity`
alone, picks the wrong overload for 266 call sites in `Y-Docs_TTPUR`, and 107
stored procedures disappear from `/find_by_sp` with neither a match nor a
diagnostic.

**Blocked by:** None.

**Status:** ready-for-agent

- [ ] `ImplementationSnapshotOperation` carries `required_parameter_count`, taken from the wrapper definition the decompiler already produces. Nothing infers it from names or types.
- [ ] The canonical behavior signature carries it, so a rebuilt contract whose optional parameters differ gets a different fingerprint instead of silently reusing the old one.
- [ ] Both method projections (`_snapshot_method_projection`, `_normalized_method_projection`) and the acceptance allowlist carry it, so it survives every path into `config/external_wrapper_contracts.json`.
- [ ] Overload selection admits a candidate when `required_parameter_count <= observed argument count <= method_arity`.
- [ ] A candidate with no `required_parameter_count` keeps today's strict arity equality. A registry written before this change selects exactly as it does now.
- [ ] An observed argument count above `method_arity` never matches.
- [ ] When more than one candidate stays applicable and the call site resolved a command-type mode, narrow to the candidates that can carry that mode argument (Mode Argument Carriage, see spec).
- [ ] Narrowing applies only when it leaves exactly one candidate. Zero or several leaves the tie exactly as it is today, including the existing shared-mode merge.
- [ ] Narrowing never runs when the call site resolved no command-type mode.
- [ ] `find_by_sp` returns the three programs that call `usp_PUR_SO_ChangeReason`'s sibling `usp_Order_PUR_SOMaintain_Modify` once the SQLObject contract is rebuilt.

## Implementation notes

- Host: `tools/StaticAnalyzerHost/WrapperDecompiler.cs` — one field on
  `ImplementationSnapshotOperation`, one argument in `ToOperation`. The
  serializer's snake_case policy gives the JSON key.
- Registry: `code_analyzer/external_wrapper_contracts.py` —
  `_canonical_operation`, `_snapshot_method_projection`,
  `_normalized_method_projection`; `service/contract_acceptance.py` — the
  optional-key allowlist.
- Matching: `code_analyzer/csharp_analysis_gateway.py` — `_wrapper_contract_method`.
  The two arity comparisons inside `candidate_matches` become one shared
  admissibility helper, and the tie-break runs on the `matching` tuple before
  `_merge_ambiguous_candidates_by_shared_mode`.
