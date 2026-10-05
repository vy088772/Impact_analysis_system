# 06 - Verify the Complete Paired Migration

**What to build:** Both repositories satisfy the complete Analyze contract and preserve valid analysis output.
The complete test and type-check results establish whether the pair is ready for deployment.

**Blocked by:** 05 - Show Failed Systems in Tools and Final Output.

**Status:** resolved

- [x] Work in both repositories after all transitive blockers complete.
- [x] Verify all acceptance requirements of the parent spec against the complete implementation.
- [x] Confirm that context_builder, grounding, agent_tools, path_selection, coverage, analyze_merge, and run_cli use typed structured Analyze data.
- [x] Confirm that adjacent Analyze callers and annotations use the changed result interface.
- [x] Remove any remaining structured Analyze dictionary defaults, legacy aliases, old return interfaces, or compatibility conversion layers.
- [x] Retain dictionary access only for genuine dynamic maps and unrelated endpoint data.
- [x] Run both repositories' agreement checks against the same sample file in the required sibling layout.
- [x] Verify actual service HTTP output against the samples and client acceptance through the production JSON parsing path.
- [x] Run focused malformed-response, recovery, merge, selection, coverage, context, grounding, tool, and output tests.
- [x] Verify that invalid initial data cannot trigger capacity recovery and that invalid recovered data cannot reach consumers.
- [x] Verify failed-System continuation, all-Systems-failed output, suppressed repeat attempts, and error privacy.
- [x] Confirm unchanged valid output, Database routing, merge identities, path order, source omission, and capacity behavior.
- [x] Run type checks for the touched service and client modules, all seven consumers, and adjacent changed callers.
- [x] Compare type errors with the pre-change baseline and introduce no new errors in the touched code.
- [x] Confirm that the committed OpenAPI export matches the live service schema and run the parity test.
- [x] Run each repository's applicable offline regression suite in its own Python environment.
- [x] Report pre-existing failures and unavailable environment requirements separately from new failures.
- [x] Do not approve completion while a new required test or type-check failure remains.
- [x] Confirm that other endpoint contracts, evidence semantics, cache versions, and catalog contents remain unchanged by this feature.
- [x] Confirm no response version field, new record-kind tag, cross-repository production import, or copied agreement file was introduced.
- [x] Record the verification outcome and the requirement to deploy both repositories together.
- [x] Do not deploy, create a branch, commit changes, or modify the parent spec as part of this ticket without separate authorization.
### Completion Notes

- This ticket changed no product code and no test code. It records verification only.
- The service commit is `f7a4f8f`. The client commit is `1075535`.
- The service baseline is `b1b2ef9^`. The client baseline is `3eb4d14^`.
- The paired migration is ready for deployment. Deploy both repositories together.
- Do not deploy the service or the client alone. A partly migrated pair rejects or misreads Analyze data.
- No deployment, branch, or commit occurred during this verification.

### Consumer and Interface Checks

- The seven consumers read structured Analyze data through model attributes.
- The four `rag_client.analyze` callers are in `run_cli`, `orchestrator`, and `agent_tools`. They use `TypedAnalyzeResult`.
- No structured Analyze field has a `.get()`, `[...]`, `setdefault()`, or `pop()` string-key read.
- The remaining dictionary reads belong to other data:
  - Path Evidence items in `context_builder`, `agent_tools`, and `path_selection`
  - flow-chain results in `agent_tools` and `rag_client`
  - `find_by_table` records in `agent_tools` and `rag_client`
  - the Analyze request payload in `AnalyzeContractError` and `_with_db_server`
- `path_selection` has two `model_dump` calls. Both are output boundaries that ticket 03 recorded:
  - the selector prompt renders capacity notes as JSON
  - a literal SP candidate keeps the complete wire record of its Database Invocation
- The client has no field alias, no `populate_by_name`, and no dictionary compatibility adapter.
- The service `AnalyzeResponse` requires all three envelope fields and forbids extra fields.
- `CodeSnippet` remains only inside `snippet_extractor`. The OpenAPI export no longer lists it because no endpoint uses it.

### Contract Boundary Checks

- The OpenAPI export changes only `AnalyzeResponse` and `ProgramAnalysis`. It adds 27 nested schemas.
- No endpoint path changed. All other existing schemas are identical to the baseline.
- Every `kind` literal in the models existed in the producer before the feature.
- The models add no response version field and no record-kind tag.
- The `contract_signature_version` and `signature_version` fields are existing wrapper evidence fields.
- Neither repository imports production code from the other repository.
- The agreement file exists only at `Impact_analysis_system/tests/cross_repository_agreement.json`.
- The client reads it through `tests/_sql_cache_fixtures.py` in the sibling layout.
- The feature changes no catalog file, `config.py`, `config/`, `data/`, `code_analyzer/`, or cache-version constant.
- The service diff changes no evidence-rating code. `evidence_status.py` in the client did not change.

### Test Results

- Service focused checks: `test_typed_analyze_response` and `test_export_openapi_schema` pass 30 tests.
- Client focused checks pass 242 tests. The files are:
  - `test_typed_analyze_response`, `test_contract_errors_in_workflow`, `test_typed_context_and_grounding`
  - `test_analyze_declared_databases`, `test_analyze_merge_definitions`, `test_database_invocation_call_site_merge`
  - `test_merged_candidates_global_resort`, `test_path_selection`, `test_coverage`
  - `test_path_evidence_wiring`, `test_transient_retrieval_retry`, `test_mypy_gate`
- These tests cover each workflow requirement of this ticket:
  - an invalid initial response stops before recovery
  - an invalid recovery response discards the initial analysis
  - malformed JSON gives a safe Contract Error without a retry
  - a later Contract Error discards the earlier partial analysis of that System
  - one failed System beside a successful System, and every System failing
  - a repeated automatic request makes no HTTP request
  - error details contain no values, source text, or dynamic keys
  - merge identities, path order, Database stamps, capacity notes, and coverage stay unchanged
  - actual service HTTP JSON passes the client parse in the client environment
  - a missing agreement file fails the test in both repositories
- Service full suite: 1,698 passed, with 2 collection errors.
- Client full offline suite: 1,551 passed, with 73 subtests passed and 0 failures.
- The client run excludes the live-service script `tests/_tmp_flow_chain_test.py`, as in tickets 01 to 05.

### Type Checks

- The client mypy gate passes 33 files with no error. The gate includes the seven consumers except `run_cli`.
- A manual check of `run_cli` and `rag_client` gives 5 errors. The baseline gave 25.
- All 5 errors are in `rag_client` candidate lookup and refresh code. The baseline `rag_client` had 6.
- `run_cli` has no error. The baseline had 19.
- The service check runs one file at a time because the tests folder has no package marker.
- The 7 existing service files that the feature touched keep 63 diagnostics. The baseline has 63.
- The 3 new service files have no error: `analyze_models`, `analyze_response_fixtures`, and `test_typed_analyze_response`.

### Pre-existing Failures and Environment Limits

- `tests/test_search_roles.py` and `tests/test_sp_tables.py` fail at collection with `KeyError: 'PUR'`.
- The cause is the unavailable ODBC Driver 17 for SQL Server. Ticket 01 recorded the same two errors.
- These errors are not new failures. No new required test or type check fails.

### Open Item

- "Contract Error" is not in the client `CONTEXT.md` glossary. Ticket 05 recorded this item.
- The spec defines the term. A domain-modeling pass can add it. This ticket does not change the glossary.
