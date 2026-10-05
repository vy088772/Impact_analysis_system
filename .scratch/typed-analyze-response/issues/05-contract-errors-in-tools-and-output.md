# 05 - Show Failed Systems in Tools and Final Output

**What to build:** Analysis tools and the command-line workflow use typed Analyze results.
A Contract Error stops only the affected System and remains visible in the returned result and final output.
Other Systems keep their valid evidence.

**Blocked by:** 03 - Use Typed Paths and Coverage; 04 - Use Typed Analysis Context and Grounding.

**Status:** resolved

- [x] Work in llamaindex-spec-rag and migrate agent_tools, run_cli, and the adjacent Analyze entry points and result annotations.
- [x] Use model attributes for structured Analyze records and keep valid summaries and command-line output unchanged.
- [x] Consume the Contract Error and safe structured details established by ticket 02.
- [x] Record one structured Evidence Gap for each System that fails its Analyze contract in the run.
- [x] Discard the failed System's partial static analysis rather than adding it to successful impact results.
- [x] Continue other Systems through the applicable existing analysis entry points.
- [x] Preserve valid Specification Evidence without describing it as a successful static analysis.
- [x] Include failed Systems in the returned result and applicable final output, even when every System fails.
- [x] Do not describe a Contract Error as zero impact, a catalog setup problem, or a need for user clarification.
- [x] Record the System failure so a repeated automatic Analyze attempt makes no new request during the same run.
- [x] Keep the recorded failure separate from successful analysis caching and ordinary missing-cache skips.
- [x] Preserve existing request-budget rules without resetting them after a failure.
- [x] Keep normal retry behavior for unrelated transient failures and existing analysis-scope rules.
- [x] Show safe System, requested Database, endpoint, error-code, field-path, and validation-category details where appropriate.
- [x] Exclude input values, raw response bodies, source snippets, SQL definitions, credentials, and connection strings from errors and logs.
- [x] Test through public analysis entry points, tools, and command-line output with controlled service responses.
- [x] Test one failed System beside a successful System and test a run where every attempted System fails.
- [x] Test a repeated automatic request for the failed System and assert that no further HTTP request occurs.
- [x] Test failure after a valid cache response and failure in a recovery response through the final workflow.
- [x] Test returned Evidence Gaps, rendered output, and error privacy without private helper assertions.
- [x] Test unchanged valid tool and command-line behavior with the migrated path, coverage, context, and grounding workflows.
- [x] Run focused workflow and output tests and introduce no new type errors in the touched slice.
- [x] Depend on tickets 03 and 04 because this ticket verifies their combined final selection and output workflow.
- [x] Do not redesign unrelated errors or endpoint response contracts.

## Comments

### Completion Notes

- The implementation commit is `0a95f1e` in llamaindex-spec-rag. The review follow-up commit is `1075535`.
- The changed modules are `agent_tools`, `orchestrator`, `run_cli`, `coverage`, and the local script `_test_ttpur_local`.
- `coverage.analyze_contract_gap` turns one `AnalyzeContractError` into one Evidence Gap of kind `analyze_contract_error`.
- The gap reason names the System, the requested Database, the endpoint, the error code, and each field path with its validation category.
- The reason reads only `error.details`. It contains no response value, source text, SQL, or connection string.
- `run_impact_analysis` records the gap and continues with the other Systems. An unrelated service error still stops the run, as before.
- `AgentRunState.record_analyze_contract_error` records one gap per System.
- The same method discards the System's earlier static analysis and marks the run as an attempted analysis.
- `analyze_system` and the forward `get_flow_chains` branch read `recorded_contract_gap` first. A recorded System gets no new Analyze request.
- The failure record is separate from `queried_systems` and from missing-cache skips. The request budget and `analyze_calls` do not reset.
- The context Evidence Gap block shows the gap without a Rephrase Suggestion.
- When every attempted System fails, the agentic answer uses a contract-failure note instead of the single-source note. The answer then lists each failed System.
- The tool text, the final output, and the CLI never call the failure zero impact, an environment setup problem, or a clarification need.
- `run_cli` modes 1 to 5 print the failed Systems through `render_analyze_contract_failures`.
- `_print_result`, `_summarize_analysis`, `summarize_collected_evidence`, and `_flatten_ui_field_events` read model attributes.
- `ImpactAnalysisResult.impact_results` and `AgentRunState.impact_results` now hold `TypedAnalyzeResult`.

### Verification

- A one-off parity script compared the old and the new `_flatten_ui_field_events` on four view-layer inputs. The candidates were identical.
- The inputs included the agreement view-layer sample and a grid with row-command events.
- The new file `tests/test_contract_errors_in_workflow.py` has 18 tests. All pass.
- The tests send controlled HTTP responses through the real `rag_client` receive path.
- The tests cover the deterministic run, the agent tools, the agentic run, and `run_cli.main()`.
- They cover one failed System beside a successful one, every System failing, a failure after a valid cache, and a failure in a recovery response.
- They also cover a repeated request without HTTP, a view-layer failure, and output privacy.
- The workflow-test stubs in 7 files now build checked results through `typed_analyze_result` and the new `view_layer_page` fixture.
- The full offline suite passes 1,551 tests and 73 subtests, with no failure. Ticket 04 had 54 failures.
- The mypy gate passes with no error. Ticket 04 had 11 errors.
- `run_cli` is not in the gate. A manual mypy run on it now passes. Before this ticket it had 19 errors about an optional `res`.
- The offline suite excludes the live-service script `tests/_tmp_flow_chain_test.py`.

### Review

- The Spec review found three gaps. The follow-up commit fixes all three, and each one has a new test:
  - A Contract Error from the view-layer request alone gave a clarification answer.
  - A System kept its earlier analysis after a later Contract Error.
  - The deterministic run lost recorded gaps when a later System failed with another error.
- The Standards review found no hard violation.
- The follow-up renames `analyze_contract_failure` to `recorded_contract_gap`. It also corrects a comment that said `run_cli` is under the mypy gate.
- The Standards review said the `typed-analyze-response` slug is missing. That is not correct: the slug is in Impact_analysis_system, not in the client repository.
- Open item: "Contract Error" is not in the client `CONTEXT.md` glossary. The spec defines the term. Ticket 06 or a domain-modeling pass can add it.
- Kept as judgement calls: the gap builder stays in `coverage`, and the catch-and-record pattern repeats in three entry points.
