# 08 — Step 2a: one listing reads every schema

**Spec issue:** 5, the listing commit

**What to build:** A refresh lists every object kind in every schema in one
query, and each object in the cache carries its own schema. A Database with
tables in `COMMON` and `HR` no longer produces a cache that holds neither. The
five caches on disk keep loading.

See "The refresh", "The object listing", "The per-object fetches", "The schema
field on the payload", "The SP Catalog", and "What each call site holds" in the
spec.

**Blocked by:** 07

**Status:** done

- [x] One listing method replaces the four. A kind table drives it, and it runs one `UNION ALL` query that selects the schema beside the name.
- [x] The method returns rows of kind, schema, and bare name as a named tuple, ordered by kind, schema, and name.
- [x] The listing method drops `sys`, `INFORMATION_SCHEMA`, `guest`, and every schema that begins with `db_`, over the returned rows. The comparison ignores case. The `db_` rule is a prefix comparison.
- [x] Seam 2: rows in `dbo`, `guest`, `db_owner`, `DB_Reports`, and `dbXyz` leave `dbo` and `dbXyz` alone.
- [x] The batch analysis entry point and the interactive menu use the new listing. The menu prints `schema.name` and passes the chosen schema on. Their Step 2a comments are removed.
- [x] Each per-object fetch takes the schema the listing reports. One helper brackets every qualified name and doubles a closing bracket inside a part.
- [x] The full-database dump loses its schema argument.
- [x] Each object entry gains a `schema` field. The cache-wide `schema` field and its three readers are deleted. The SP Catalog drops its default-schema argument, and a fallback match keeps `proven` with the Unproven Schema reason.
- [x] The SQL Execution Graph builder reads each object's own `schema` field, and reads `dbo` when that field is absent.
- [x] The cached object lookup loses both `dbo` fallbacks. An empty schema on either side matches nothing.
- [x] The dump records a `name_collisions` entry for a bare name that two schemas hold in one kind.
- [x] The fixture's payload builder stops writing the cache-wide key. A cache store case asserts that a saved data file holds no top-level `schema` key.
- [x] One gateway test case: a caller states a schema, the catalog holds the name without one, and the result is a match with the Unproven Schema reason.
- [x] No version rises. The `sample_cache` entry is regenerated.
- [x] The whole suite of this repository passes.
- [ ] This commit deploys together with ticket 09. No refresh runs between them. (Open: ticket 09 is not done.)

## Notes (implementation, 2026-09-29)

- **Commit.** One commit, `4e5df1a`, holds the whole listing commit. Its
  message names each test file it changes.
- **Changed files.** Listing and dump: `code_analyzer/sql_analyzer.py`
  (`ObjectListing`, `_LISTING_KINDS`, `list_objects`, `quote_name`,
  `dump_all_sql_objects`). Catalog and gateway:
  `code_analyzer/csharp_analysis_gateway.py`. Readers:
  `service/analyze_service.py`, `service/sql_execution_graph.py`,
  `service/sql_cache_store.py`. Fixture: `tests/sql_cache_fixtures.py`,
  `tests/cross_repository_agreement.json` (`sample_cache`). Doc:
  `docs/流程圖_進階.md` (method names only).
- **Listing.** `list_objects(kind=None)` runs one `UNION ALL` query over the four
  `INFORMATION_SCHEMA` views and binds no parameter. The excluded-schema rule
  runs over the rows. The optional `kind` argument keeps one kind. The batch
  entry point and the menu use it, so the "procedures only" step has one form.
  `analyze_all_procedures` lost its `schema` argument.
- **Menu.** It prints `schema.name` and passes the chosen schema on. The ticket
  does not say what a typed name does. `_match_typed_procedure` accepts a typed
  name only when one listed procedure matches it. A bare typed name that two
  schemas hold is refused with a message. The old code used `dbo` here.
- **Bracket helper.** `quote_name` brackets each part and doubles a closing
  bracket. It serves the three sites the spec names and one more:
  `_get_sp_basic_info` composed a name for `OBJECT_ID` in the same way. The
  existing test that pinned `dbo.usp_Long` now pins `[dbo].[usp_Long]`.
  `get_object_definition` always quotes `(schema, name)`. Its old rule read a
  name that held a dot as already qualified, which is wrong for a listed name.
- **Payload.** Each entry states `name` then `schema`. The dump holds no
  top-level `schema`. `name_collisions` is always written, as a list. It is empty
  when no collision exists. An entry holds `kind`, the name as the first row
  wrote it, and the schemas sorted without case. A collision folds case.
- **Readers deleted.** The validity check, the graph builder, and the catalog
  build. `refresh_sql_source` also read the field for `db_schema`. It now returns
  the `schema` argument. Ticket 09 removes `db_schema`.
- **Graph builder.** `_object_schema` reads the object's `schema` field, then the
  schema written in the name, then `dbo`. The middle step keeps the old result
  for a hand-written payload whose name states a schema. A real old cache holds
  bare names, so the result equals the spec text.
- **Cached object lookup.** Both `dbo` fallbacks are gone. An old cache holds no
  per-object `schema`, so every node of an old cache now reports `stale_path`
  until the next refresh. This follows "An empty schema on either side matches
  nothing".
- **SP Catalog: a deviation to decide.** The spec's two-bucket rule says a
  qualified name that misses the full bucket falls back to the bare bucket. The
  bare bucket holds every name. A literal reading matches `sales.X` to `HR.X`,
  and the existing test `..._does_not_cross_same_name_schemas` forbids it. The
  SP Catalog section says "a qualified call still matches a catalog entry that
  states no schema". `SpCatalog` therefore holds a third set,
  `schemaless_procedures_by_database`, and the fallback reads only that set.
  `match_reason` returns `None` for a miss, `""` for an exact match, and
  `"unproven_schema"` for the fallback. `contains` wraps it. The Object Location
  Index in ticket 11 must decide the same question. **The spec text needs one
  sentence that says which rule holds.**
- **Reason on a proven match.** The gateway sets `reason="unproven_schema"` on a
  `DbInvocation` and on an `EmbeddedProcedureTarget`. The Evidence Status stays
  `proven`, and `unresolved_reason` stays empty. `reason` on the Execution Path
  now shows the value for such a path. The old test
  `test_bare_catalog_entries_are_scoped_to_default_schema_for_qualified_calls`
  stated the removed `dbo` rule, so the new case replaces it.
- **Line endings.** Nine files use CRLF. A first pass with `Path.write_text`
  converted them to LF. The code review found it. The commit keeps CRLF.
- **Suite.** `pytest tests/ --ignore=tests/test_search_roles.py
  --ignore=tests/test_sp_tables.py`. Main tree after: 1109 passed, 16 failed. The
  same 16 as ticket 07. Baseline in a worktree at `ef8bc1f`: 1031 passed, 15
  failed, 57 skipped. Differences by id, none from this change: the four
  path-dependent ids in the main tree only (`test_real_iqcs_refresh...` and three
  in `test_sqldbcontext_real_calls_resolve.py`), and three worktree-only failures.
  New failures this change caused, fixed before the commit: none remain.
- **mypy.** No new error on the five changed modules. Six errors disappear with
  the four deleted methods.
- **Review items left open (judgement calls).** `dump_all_sql_objects` keeps four
  similar progress loops, as before. The kind strings repeat as literals. The
  `sql_cache_store` module docstring still says "指定 schema"; ticket 09 owns it.
  `CONTEXT.md` has no `unproven_schema` entry yet; ticket 12 owns it.
- **Deployment.** This commit deploys with ticket 09. No refresh runs between
  them. A refresh now writes per-object schemas, but the cache filename and the
  request still carry one schema until ticket 09.
