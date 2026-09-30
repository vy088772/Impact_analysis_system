# 07 — A C# call with no schema resolves to dbo

**What to build:** An analyst reads a C# call to a procedure that states no schema, and the SP Catalog names `dbo.name` as the target when the catalog holds it. The quick single-procedure analyzer follows the same rule: the schema the name states, else `dbo`. Its query for "the one schema that holds the name" goes away.

See "The C# side" and user stories 21 and 22 in the spec.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A failing gateway test comes first: a C# call to `usp_Load` with no schema, over a catalog that holds `dbo.usp_Load` and `COMMON.usp_Load`, matches `dbo.usp_Load` with no Unproven Schema reason.
- [x] The same call over a catalog without `dbo.usp_Load` gets the Unproven Schema match reason. Before this ticket, that match gave an empty reason.
- [x] The quick analyzer's unstated schema tests change to "stated, else `dbo`". A name that `dbo` does not hold does not exist.
- [x] The quick analyzer's `schema` argument keeps no default, and its test still checks that.
- [x] The whole suite shows no new failure.

## Comments

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `code_analyzer/csharp_analysis_gateway.py`: `SpCatalog.match_reason()` asks a call with no schema for `dbo.name` in the full bucket. A hit gives an empty reason. A miss that the bare bucket holds gives `unproven_schema`. New `SpCatalog.resolved_schema()` returns the stated schema, else `dbo` when the catalog holds `dbo.name`, else `None`. The two catalog match sites (`EmbeddedProcedureTarget` and `DbInvocation`) record that schema, so a resolved call shows `procedure_schema == "dbo"`.
- `code_analyzer/sql_analyzer.py`: `quick_analyze_sp()` takes the stated schema, else the `schema` argument, else `DEFAULT_SCHEMA` (`dbo`, from `schema_resolution`). `_only_schema_holding()` is removed. The `schema` argument keeps no default.
- `tests/test_csharp_analysis_gateway.py`: 2 new tests (dbo match with no reason; no `dbo` keeps `unproven_schema`).
- `tests/test_sql_analyzer_unstated_schema.py`: the unstated schema tests now say "stated, else `dbo`".

Suite: 16 tests fail before and after this ticket (wrapper registry, sqldbcontext and `program_refresh` tests). No new failure. `tests/test_search_roles.py` and `tests/test_sp_tables.py` need a live database and fail at collection, before and after.
The two edited source files and one test file use CRLF line endings. Keep them.

**Whole-feature review, 2026-09-30** (`/code-review` from `b865587` to `154ad57`, then the fixes).

- The spec said that the call "keeps" the Unproven Schema match reason. That premise was wrong: before this ticket, a call with no schema that matched the bare bucket gave an empty reason. The spec and the second box above now say "gets".
- `SpCatalog.resolved_schema()` calls `schema_resolution.resolve()` (commit `601b997`). It restated the `dbo` step before. Behaviour does not change.
- `quick_analyze_sp()` keeps its own line (`written.schema or schema or DEFAULT_SCHEMA`). It has no object listing, and its `schema` argument sits between the two steps, so `resolve()` does not fit it.
