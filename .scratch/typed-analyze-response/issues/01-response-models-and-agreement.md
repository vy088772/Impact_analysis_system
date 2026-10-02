# 01 - Establish the Analyze Response Models and Agreement

**What to build:** A valid service response satisfies independently maintained service and client models.
Both repositories check one agreement file.
Invalid fields fail a contract check instead of appearing as empty evidence.

**Blocked by:** None - can start immediately.

**Status:** resolved

- [x] Work in both Impact_analysis_system and llamaindex-spec-rag.
- [x] Use the parent spec, Keep the Analyze Response Typed Across the HTTP Seam, as the governing contract.
- [x] Declare the complete known Analyze Response shape with independent Pydantic models in both repositories.
- [x] Declare Pydantic as a direct client dependency; do not import the sibling's production models.
- [x] Replace the service's untyped Analyze records with nested models while preserving existing valid JSON shapes.
- [x] Define a separate client Typed Analyze Result model for merged data and client additions.
- [x] Reuse local nested types where the original and merged contracts agree.
- [x] Require every service-emitted envelope field and ProgramAnalysis container in the client model.
- [x] Accept legal empty containers, legal nulls, and legitimate omitted nested fields.
- [x] Preserve omitted fields separately from null fields during service serialization.
- [x] Reject missing required fields, renamed fields, unknown structured fields, wrong primitive types, and illegal nulls.
- [x] Reject numeric strings for numbers and booleans for integers.
- [x] Allow dynamic keys only in actual maps with declared value types.
- [x] Describe supported record variants without adding kind tags or changing their meaning.
- [x] Preserve separate invocation, wrapper, and conclusion evidence concepts; reject unknown invocation and wrapper ratings.
- [x] Keep one agreement file in the service repository and use the existing client sibling-repository sample helper.
- [x] Fail an agreement test when its sample file is missing; do not skip the check.
- [x] Cover empty responses and nonempty methods, snippets, definitions, diagnostics, views, related programs, invocations, paths, and shared-component contributions.
- [x] Cover supported variants, omitted fields, legal nulls, dynamic maps, and evidence vocabularies in the samples.
- [x] Compare declared structured field sets with the samples so an unrepresented added field fails the agreement check.
- [x] Test an actual service HTTP response with controlled scan and cache inputs, not only handwritten sample acceptance.
- [x] Test client model acceptance through the public JSON parse interface with the same samples and actual service JSON.
- [x] Test invalid cases through the JSON parse interface, including malformed JSON.
- [x] Update the OpenAPI export and pass its parity test without changing other endpoint contracts.
- [x] Run focused agreement and service-response checks in each repository's own environment.
- [x] Introduce no legacy field aliases, response version field, or dictionary compatibility adapter.
- [x] Leave the client runtime cutover to ticket 02; this ticket adds models without a temporary runtime conversion layer.
- [x] Keep this ticket undeployed until ticket 06 approves the complete paired migration.

## Comments

### Completion Notes

- The affected service function is `analyze`.
- The service now validates its nested records when it builds each `ProgramAnalysis`.
- The service preserves valid JSON field names, empty sections, nulls, and omitted optional fields.
- The client declares independent `AnalyzeResponse` and `TypedAnalyzeResult` models.
- The client declares Pydantic 2.13.4 as a direct dependency.
- The service requires Pydantic 2.11 or newer for its alias serialization setting.
- The client runtime does not use these models yet.
- Ticket 02 owns the runtime change. Ticket 06 owns approval for paired deployment.
- No deployment occurred. No other endpoint contract changed.
- Both environments check one agreement file through JSON parsing.
- The tests compare each structured field set with the represented sample fields.
- The tests reject malformed JSON and invalid nested records.
- The tests also remove and rename every required field in the represented records.
- Each repository verifies that a missing agreement file fails its test.
- A controlled HTTP request produces nonempty invocation, path, definition, snippet, and view evidence.
- The client parses that actual response in its own environment.

### Verification

- Final service contract checks: 27 passed.
- Final client contract checks: 30 passed.
- Service model-access regression checks: 71 passed.
- OpenAPI export parity checks: 3 passed.
- All other endpoint paths and their 29 referenced schemas match the starting export.
- The service full suite ran once: 1,694 passed, with two collection errors.
- Both collection errors require the unavailable ODBC Driver 17 for SQL Server.
- The affected existing tests are `test_search_roles` and `test_sp_tables`.
- The client full offline suite ran once: 1,460 passed, with 73 passed subtests.
- The client run excluded the existing live-service scratch script.
- The full runs preceded review. The final contract checks include the added review cases.
- New models, fixtures, and contract tests pass mypy in their own environments.
- Seven existing service files retain the same 63 mypy diagnostics as the starting baseline.
- The editor reports no errors in the changed Python files.

### Review

- Independent Standards and Spec reviews examined both repository diffs.
- Standards found no documented rule violation.
- Spec found two service test gaps. Both gaps now have passing tests.
- The service accepts an internal overload tuple but keeps strict string elements.
- The client accepts only the JSON array representation of that field.
- The actual HTTP agreement check uses each repository's documented `.venv` environment.
- Test assertions use the public `model_fields_set` API to distinguish absent fields.
- Compact and full paths remain separate records because their field sets differ.
- Explicit construction validation avoids new constructor type errors without a dictionary compatibility interface.
