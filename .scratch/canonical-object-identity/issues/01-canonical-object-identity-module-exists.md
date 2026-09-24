# 01 — The Canonical Object Identity module exists and states its rule

**Spec issue:** 0

**What to build:** One module owns the rule that turns a written SQL object name
into a comparison key. The module exists and passes its own string tests. No
site calls it yet, so no answer changes. The cross-repository fixture file
exists and holds the `object_names` case list. The test fixture builder in
ticket 02 then parses a written name with this module.

See "The Canonical Object Identity module", "Cross-repository coordination",
and "Seam 4" in the spec.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] The module is one file at the top level of this repository, beside `config`, named after the glossary term. It imports nothing from this project.
- [x] The module exports a frozen value type with four fields: server, database, schema, and bare name. An empty field means "not stated", never "default".
- [x] The module exports a parse function, a bare-key function, a full-key function, and a case-preserving variant of the bare name.
- [x] The parse function returns an empty schema for a name that states none. It takes no default-schema argument.
- [x] A full key always holds three segments, and an empty part stays an empty segment. `Orders` gives `..orders`.
- [x] No key reads the server field. The parse of `srv.PUR.dbo.Users` holds the server `srv`, and its full key holds three segments and no server.
- [x] The bracket form `[db].[schema].[table]` gives the same keys as `db.schema.table`.
- [x] All case folding uses `casefold`.
- [x] The cross-repository fixture file sits under the test directory as JSON. It holds the `object_names` list. Each case states an input name, the three parsed parts, the bare key, and the full key.
- [x] The list holds the two procedure-name cases: `usp_Load` gives an empty schema, `usp_load`, and `..usp_load`. `[COMMON].[usp_Load]` gives no bracket, `usp_load`, and `.common.usp_load`.
- [x] The Seam 4 test reads that list, passes strings in, and reads strings out. It builds no graph and opens no cache.
- [x] No existing site calls the module. The whole suite passes, and every existing test reports the same outcome as before.

## Comments

**Implementation notes (2026-09-24)**

- **Files.** This ticket adds three files: `canonical_object_identity.py`,
  `tests/test_canonical_object_identity.py`, and
  `tests/cross_repository_agreement.json`. It changes no existing file.
- **Names.** The value type is `ObjectName`. The functions are `parse`,
  `bare_key`, `full_key`, and `bare_name`. `bare_name` is the case-preserving
  variant. Each key function accepts an `ObjectName`, a written name, or `None`.
- **Parse rule.** The parse removes every bracket and splits the name on dots.
  It strips the whitespace around each part. It reads the parts from the right,
  so it keeps an empty middle part: `PUR..Orders` gives the schema `""`. More
  than four parts keep only the last four.
- **Parsed parts keep their written case.** Only the keys use `casefold`. The
  fixture states the parts in their written case.
- **Fixture file.** The file name is `tests/cross_repository_agreement.json`.
  The spec gives no name. The `object_names` list holds nine cases. Each case
  states `database`, `schema`, and `name`, but not the server. The spec asks
  for three parts. A separate test covers the server.
- **Divergences for the tickets that wire the sites.** The code review found
  these differences from today's site rules. No site calls the module yet, so
  no answer changes in this ticket.
  - `sp_fetcher._normalize` and `csharp_analysis_gateway.normalize_procedure_name`
    use `lower`. The module uses `casefold`. This is the one intended Step 1
    change ("The behaviour change in Step 1").
  - `sql_execution_graph` strips a double quote in `_clean_identifier`. The
    module strips only brackets.
  - `sql_execution_graph`'s splitter drops empty segments before it reads the
    schema. For `PUR..Orders` it reads the schema `PUR`. The module reads an
    empty schema. The spec does not name this difference.
  - Today's fetchers strip the whole string, not each part. For `dbo. Orders`
    they give ` orders`. The module gives `orders`.
- **Code review.** The Standards review found no violation of a documented
  standard. The test for "imports nothing" now reads the module through `ast`.
  The name `full_key` stays, because the spec names that function. The
  glossary has no entry for Canonical Object Identity yet. Ticket 12 owns the
  documents. The Spec review found no missing requirement.
- **Test suite.** The command is `pytest tests/
  --ignore=tests/test_search_roles.py --ignore=tests/test_sp_tables.py`. Those
  two files need a live database at collection. The result is 1053 passed and
  16 failed. The base commit `9820c9a` gives 1036 passed and the same 16
  failures. The 17 new tests make the difference.
