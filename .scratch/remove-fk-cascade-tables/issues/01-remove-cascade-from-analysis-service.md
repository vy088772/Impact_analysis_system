# 01 — Remove the FK cascade table from the analysis service

**What to build:** The analysis service no longer reports a FK cascade table. An
analyst who calls the analyze endpoint or the flow chain endpoint gets the
program outline, the source code, the stored procedures and the tables that the
program really reads or writes. The response holds no cascade table field, and
neither endpoint accepts a cascade depth.

The service removes the resolver module that inferred a relation from a primary
key name. The service removes the cascade depth from both request schemas. Both
fields default to 1 today, which contradicts the deployed behaviour, so the
removal also ends that contradiction. The service removes the cascade field from
the program result and from the forward chain result.

This is a breaking change to the API contract. No caller outside the two
repositories reads the field, so the removal is direct. The response does not
keep an empty field.

The committed OpenAPI export is the one seam for this work. Regenerate it after
the schema change, and the guard test proves the contract really moved.

**Blocked by:** None — can start immediately. This ticket does not gate ticket
02, and ticket 02 does not gate this one. The request schemas ignore an unknown
field, so a caller that still sends the cascade depth keeps working.

**Status:** done

- [x] The analyze endpoint rejects no request, and silently ignores a cascade depth that an old caller still sends.
- [x] The analyze response holds no cascade table field.
- [x] The flow chain forward result holds no cascade table field.
- [x] Neither request schema declares a cascade depth.
- [x] The resolver module and its dedicated test file no longer exist.
- [x] No test case in this repository passes a cascade depth argument.
- [x] The committed OpenAPI export matches what the live application produces.
- [x] The whole test suite of this repository passes.

**Note (2026-09-22):** Removed `service/fk_resolver.py` and
`tests/test_fk_resolver.py`. Removed `fk_depth` from `AnalyzeRequest` and
`FlowChainRequest`, `related_tables` from `ProgramAnalysis`, and
`related_tables_fk` from `flow_chain_builder.build_forward_chain`'s result
dict (also dropped its now-unused `fk_depth` parameter). Removed the two
call sites in `analyze_service.py` and one in `flow_chain_builder.py` that
built the field, plus the ten `fk_depth=` test arguments across five test
files. `AnalyzeRequest`/`FlowChainRequest` have no `model_config`, so
Pydantic's default `extra="ignore"` already makes an old caller's cascade
depth argument silently ignored — verified directly with
`AnalyzeRequest(fk_depth=5)`. Regenerated `docs/openapi/openapi.json`; the
diff removes exactly the two `fk_depth` fields and the one `related_tables`
field, nothing else. `python -m tools.export_openapi_schema --check` and
`tests/test_export_openapi_schema.py` both pass.

Left two comments (`service/sql_cache_store.py`, `code_analyzer/sql_analyzer.py`)
pointing at the now-deleted `fk_resolver.py` — reworded them to say the
resolver was removed, since `tables[].primary_keys` collection itself is
still used by other code and stays out of this ticket's scope.

Full suite: `python -m pytest` (excluding `tests/test_search_roles.py` and
`tests/test_sp_tables.py`, which fail to even collect in this environment —
no ODBC driver installed, unrelated to this change) — 1036 passed, 16
failed. Confirmed by running the same 16 on `git stash` (pre-change code):
identical 16 failures, same error messages (missing .NET decompile
fixtures, stale contract registry keys). This change adds zero new
failures.

Out of scope for this ticket, flagged for whoever picks up ticket 03: this
repo's `docs/adr/` already has an `0031-retire-the-legacy-dependency-dictionary-pipeline.md`,
so the new ADR ticket 03 asks for cannot also be numbered 0031 — it needs
the next free number (0032).
