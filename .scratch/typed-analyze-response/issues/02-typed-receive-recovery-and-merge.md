# 02 - Keep Receive, Recovery, and Merge Typed

**What to build:** The client's public Analyze entry point returns a Typed Analyze Result.
It checks each response before recovery or merge can use its fields.
Valid multi-Database analysis keeps the same facts and routing identities.

**Blocked by:** 01 - Establish the Analyze Response Models and Agreement.

**Status:** resolved

- [x] Work in llamaindex-spec-rag and use the models established by ticket 01.
- [x] Parse each successful Analyze HTTP response once before reading any structured field.
- [x] Use the same parse entry for declared-Database, explicit-target, unscoped, and recovery responses.
- [x] Return a typed empty result without an HTTP request when the program request is empty.
- [x] Reject invalid initial data before capacity metadata can trigger a recovery request.
- [x] Check a recovery response before it replaces the initial response.
- [x] Keep capacity inspection, recovery, analyze_merge, and the public Analyze return typed.
- [x] Keep unrelated endpoint contracts and genuine dynamic maps unchanged.
- [x] Preserve the Lookup Database Set and explicit Database target routing.
- [x] Preserve the existing request budget, recovery limit, and residual capacity notes.
- [x] Preserve normal missing-SQL-cache skips and the existing unscoped request when declared caches are unavailable.
- [x] Preserve Database Invocation identity, source-span identity, resolved-view precedence, and Wrong-cache Non-resolution handling.
- [x] Preserve distinct same-cache branches, cross-Database paths, definition deduplication, and service-supplied relevance ordering.
- [x] Add complete Database identity pairs only to new merged records; do not change the original response.
- [x] Preserve read and skipped Database facts in typed coverage data.
- [x] Raise a distinct Contract Error for malformed JSON or failed model validation through the existing service-error handling interface.
- [x] Keep a stable error code with safe System, requested Database, endpoint, field-path, and validation-category details.
- [x] Exclude input values, response bodies, source text, SQL definitions, credentials, and connection strings from error details.
- [x] Stop that System's request expansion after a Contract Error and do not return its earlier partial cache results.
- [x] Do not treat a Contract Error as a missing cache or a transient failure eligible for automatic HTTP retry.
- [x] Keep existing transient retries for unrelated transport and server failures.
- [x] Test the public Analyze entry point with a controlled HTTP transport for initial and recovery validation failures.
- [x] Test malformed JSON and a failure after an earlier valid cache response.
- [x] Test typed empty results, explicit routing, declared routing, normal skips, and unscoped requests.
- [x] Test unchanged merge behavior through Analyze and the existing merge interface where useful.
- [x] Test that merging leaves the input models unchanged and preserves capacity notes and coverage data.
- [x] Use focused type checks for receive, recovery, and merge; record failures from consumers not yet migrated.
- [x] Add no legacy return interface or model-to-dictionary adapter to keep unmigrated consumers working.
- [x] Promise full-suite compatibility only after the consumer migrations and ticket 06.

## Comments

### Completion Notes

- The implementation commit is `59f4e03` in llamaindex-spec-rag.
- The affected public functions are `rag_client.analyze` and `merge_analyze_responses`.
- Analyze now returns a Typed Analyze Result instead of a dictionary.
- The client checks each successful response before recovery or merge reads its fields.
- All Analyze request routes use one JSON model parse entry.
- An empty program request returns a typed empty result without an HTTP request.
- The client keeps capacity inspection, recovery, merge records, and coverage data typed.
- A Contract Error is an invalid Analyze response, not missing evidence or a missing SQL cache.
- `AnalyzeContractError` extends the existing `ImpactServiceError` interface.
- The stable error code is `analyze_contract_error`.
- The error details identify the System, requested Database, endpoint, field path, and validation category.
- The error details exclude response values and response bodies.
- The client hides unknown field names and dynamic map keys in error paths.
- A Contract Error stops the current System's request expansion and prevents a partial return.
- The client preserves transport retries, cache skips, routing identities, and merge rules.
- Recovery retains the original request fields and the existing 60-path limit.
- Capacity notes describe residual omissions after recovery, as before.
- Merge creates new Database-stamped path records and leaves the original models unchanged.
- Merge omits the optional capacity-note field when no residual note exists.
- Existing receive and merge tests now use complete agreement-based wire fixtures and model attributes.
- The fixture builders exist only in tests. The client has no dictionary compatibility adapter.

### Verification

- The focused contract and public Analyze test file passes all 76 tests.
- The existing definition, call-site, and global-sort merge files pass all 19 tests.
- The declared-routing, question, and retry files pass 45 tests, with one deferred consumer failure.
- The final full offline suite passes 1,507 tests and 73 subtests.
- The suite retains two failures that require the later consumer migration tickets.
- `test_path_expansion_opens_the_sql_cache_that_produced_the_path` still reaches dictionary access in `path_selection`.
- Ticket 03 owns that path-selection migration.
- `test_gated_modules_pass_mypy` reports five errors in `agent_tools` and `orchestrator`.
- Those consumers still expect dictionary Analyze results.
- The focused model and merge mypy check passes.
- The receive, recovery, and merge check adds no new diagnostics.
- The full `rag_client` check retains five existing diagnostics in candidate lookup and refresh code.
- The offline suite excludes the existing live-service script `tests/_tmp_flow_chain_test.py`.
- The editor reports no errors in the changed Python files.
- The migration is not ready for deployment. Ticket 06 owns full-suite compatibility and paired deployment approval.

### Review

- Independent final Standards and Spec reviews report no findings.
- Both reviews use the starting client commit `3eb4d1414105133beb866d0edcf4a162235cb39f` as the fixed baseline.
- The reviews cover the current ticket changes, not the deferred consumer migrations.
- No service endpoint contract, catalog, credential, or cache content changed.
