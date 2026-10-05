# 04 - Use Typed Analysis Context and Grounding

**What to build:** The context builder and grounding checks use checked Analyze records.
Valid data produces the same supported analysis content and known-name checks without silent dictionary defaults.

**Blocked by:** 02 - Keep Receive, Recovery, and Merge Typed.

**Status:** resolved

- [x] Work in llamaindex-spec-rag and migrate the Analyze inputs of context_builder and grounding.
- [x] Use model attributes for program data, methods, snippets, definitions, related programs, views, invocations, and paths where consumed.
- [x] Preserve legitimate optional source fields without inventing source text or definitions.
- [x] Preserve the returned context, known-name sets, evidence labels, and supported output order for valid inputs.
- [x] Preserve existing source and definition deduplication where the current context workflow applies it.
- [x] Keep genuine dynamic maps and unrelated Path Evidence or flow-chain data in their existing forms.
- [x] Do not convert checked Analyze records into dictionaries before rendering or grounding checks.
- [x] Update adjacent call-site annotations and focused fixtures required by the typed input contract.
- [x] Test observable rendered context and grounding results with empty and nonempty checked models.
- [x] Include supported variants and optional source fields rather than only a minimal program sample.
- [x] Reuse existing rendering and path-evidence wiring test patterns without testing private call order.
- [x] Run focused context and grounding tests and introduce no new type errors in the touched slice.
- [x] Add no new public test interface or dictionary compatibility adapter.
- [x] Keep this ticket independently executable from ticket 03 after ticket 02 completes.

## Comments

### Completion Notes

- The implementation commit is `4daafc3` in llamaindex-spec-rag.
- The changed modules are `context_builder` and `grounding`.
- The adjacent annotations in `finalize_analysis` and `write_output` now name `TypedAnalyzeResult`.
- `build_context` reads programs, methods, snippets, definitions, invocations, paths, view layers, and related programs through model attributes.
- `verify_grounding` builds its known-name sets from the same model attributes.
- The view-layer code selects each block variant by its model class instead of the `kind` string.
- Compact paths keep priority over full Execution Paths.
- An omitted compact-path `unresolved_reason` still renders `reason=unresolved`, as before.
- The check uses `model_fields_set`, as `path_selection` does.
- Related programs keep the `(class, method, file)` deduplication, the first depth, the merged caller list, and the first nonempty snippet.
- A related program without a snippet gets no code block. The client invents no source text.
- `code_retriever` still takes `{label, text}` dictionaries.
- The client builds those dictionaries at that boundary and maps the selection back to the checked `Snippet` records through `_idx`.
- Path Evidence rendering, evidence gaps, unread systems, and flow-chain text keep their existing forms.
- The client adds no dictionary compatibility adapter and no new public test interface.

### Verification

- A one-off parity script rendered 48 outputs from the old dictionary code and the new typed code.
- The outputs were byte-identical.
- The script covered `build_context`, `verify_grounding`, and `_build_known` with these inputs:
  - a rich program, an empty-section program, empty results, and no results
  - budgets of 24000, 40, and 0 characters
  - embedding selection and AI annotation turned on and off
  - an omitted `unresolved_reason` and related-program deduplication
- The new file `tests/test_typed_context_and_grounding.py` has 18 tests. All pass.
- The tests cover empty and nonempty checked models, all view-layer variants, and optional source fields.
- They also cover definition selection, invocation and path ratings, embedding selection, and grounding.
- `test_evidence_gaps_reporting` and the `build_context` case in `test_path_evidence_wiring` now use typed fixtures.
- The focused context, coverage, wiring, and grounding files pass 122 tests and fail 2.
- The 2 failures occur in `agent_tools._summarize_analysis`. Ticket 05 owns that consumer.
- `context_builder`, `grounding`, `finalization`, and `output_writer` pass mypy with no errors.
- The full offline suite passes 1,484 tests and 68 subtests, with 54 failures. Ticket 03 had 57.
- The fixes in this ticket clear 6 failures:
  - 4 in `test_evidence_gaps_reporting`
  - 1 in `test_coverage`
  - 1 in `test_path_evidence_wiring`
- 3 new failures occur in `test_architecture_modules.AnswerSynthesisSettingTests`.
- Their workflow stub gives a dictionary Analyze result to `finalize_analysis`, which then calls `verify_grounding`.
- A typed shared stub made more agentic tests fail inside the unmigrated `agent_tools`. Ticket 05 owns those stubs.
- The mypy gate reports 11 errors. Ticket 03 had 10.
- The `context_builder.py:1321` error is gone.
- `orchestrator.py:310` and `:1414` are new. Those `finalize_analysis` callers still annotate their local list as a dictionary list.
- Ticket 05 owns those result annotations, as ticket 03 recorded for `select_path_evidence`.
- The offline suite excludes the live-service script `tests/_tmp_flow_chain_test.py`.

### Review

- The Standards review found no hard violations.
- The review fixes give the two view unions separate private names, `_ViewBlock` and `_ViewNode`.
- The `output_writer` import of `TypedAnalyzeResult` moved under `TYPE_CHECKING`.
- The repeated block-type switch existed before as a `kind` switch. This ticket keeps it.
- The Spec review found no missing requirement and no behaviour change.
- The Spec review notes that the omitted-reason output depends on merge keeping `model_fields_set`.
- `analyze_merge` keeps that set today, and `path_selection` depends on it the same way.
