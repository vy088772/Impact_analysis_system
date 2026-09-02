# 01 — Overload selection reads Required Parameter Count and Mode Argument Carriage

**What to build:** A call to an external wrapper method binds to the overload C#
itself would bind it to, when the difference between the candidates is a trailing
optional parameter. Today the gateway compares argument count to `method_arity`
alone, picks the wrong overload for 266 call sites in `Y-Docs_TTPUR`, and 107
stored procedures disappear from `/find_by_sp` with neither a match nor a
diagnostic.

**Blocked by:** None.

**Status:** resolved

- [x] `ImplementationSnapshotOperation` carries `required_parameter_count`, taken from the wrapper definition the decompiler already produces. Nothing infers it from names or types.
- [x] The canonical behavior signature carries it, so a rebuilt contract whose optional parameters differ gets a different fingerprint instead of silently reusing the old one.
- [x] Both method projections (`_snapshot_method_projection`, `_normalized_method_projection`) and the acceptance allowlist carry it, so it survives every path into `config/external_wrapper_contracts.json`.
- [x] Overload selection admits a candidate when `required_parameter_count <= observed argument count <= method_arity`.
- [x] A candidate with no `required_parameter_count` keeps today's strict arity equality. A registry written before this change selects exactly as it does now.
- [x] An observed argument count above `method_arity` never matches.
- [x] When more than one candidate stays applicable and the call site passed a command-type argument, narrow to the candidates that can carry that mode argument (Mode Argument Carriage, see spec).
- [x] Narrowing applies only when it leaves exactly one candidate. Zero or several leaves the tie exactly as it is today, including the existing shared-mode merge.
- [x] Narrowing never runs when the call site passed no command-type argument. `wrapper_mode` cannot gate this — the scan reports `command_type_argument_observed` for it.
- [x] One tied candidate that cannot be judged for carriage abandons the narrowing instead of losing it.
- [x] `find_by_sp` returns the programs that call `usp_Order_PUR_SOMaintain_Modify` once the SQLObject contract is rebuilt.

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
- Observation: `tools/StaticAnalyzerHost/CSharpAnalyzer.cs` —
  `HasModeLiteralArgument`, reported as `command_type_argument_observed` on the
  raw invocation. Raw scan facts are versioned, so `service/scan_store.py`'s
  `_CACHE_VERSION` goes to 29.
- The fingerprint widening is recorded in
  `docs/adr/0014-required-parameter-count-joins-the-contract-behavior-signature.md`;
  both new terms are in `CONTEXT.md`.

## Comments

Measured on the `Y-Docs_TTPUR` scan, contract `sqlobject-4195c73e585b`:
411 → 510 distinct stored procedures named, none lost. `find_by_sp` and
`llamaindex-spec-rag`'s `find_programs_by_sp` both return the callers of
`usp_Order_PUR_SOMaintain_Modify` and `usp_Evaluate_PUR_MasterEdit_Enable`,
which returned nothing before.

`usp_PUR_SO_ChangeReason` still returns nothing, as the spec's "What this does
not fix" section says it will: its three call sites reach the procedure through
`CreateTable(sql, "SP")`, whose two-argument overload really does treat `"SP"`
as a table name and really does run the procedure name as inline SQL text.
