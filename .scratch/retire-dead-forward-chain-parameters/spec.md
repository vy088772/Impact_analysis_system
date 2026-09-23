# Retire Dead Forward-Chain Code and Parameters

Status: ready-for-agent

## Problem Statement

The forward direction of the relationship chain (`flow_chain_builder.build_forward_chain()`) carries surface that no code reads:

- `build_forward_chain()` declares six parameters that its body never reads: `sp_relations`, `root`, `database_alias`, `db_server`, `db_name`, and `max_sp_depth`. The formal SP chain now comes only from the SQL Execution Graph. The docstring for `sp_relations` already says the parameter stays only for old callers.
- `flow_chain_builder._expand_sp_chain()` has no caller anywhere in the repo. It is the only caller of `sp_call_fetcher.fetch_called_sp_names()`. Thus the whole `sp_call_fetcher` module is dead too.
- `analyze_service.flow_chain()` builds three local values (`database_alias`, `db_server`, `db_name`) only to pass them into these dead parameters.
- The module docstring of `flow_chain_builder` still says the forward chain expands nested SP calls recursively. It also names `sp_call_fetcher` in its list of known limits. Neither statement is true now.
- The module docstring of `view_fetcher` says that the module connects to SQL Server live when the cache has no entry. ADR-0011 removed live lookup. The function body skips a name that the cache does not hold.

An engineer who reads the `build_forward_chain()` signature cannot tell which inputs change the result. An engineer who reads the module docstrings gets a wrong model of the forward chain.

The previous cleanup (`.scratch/remove-unused-fetcher-parameters/`) found this surface during code review and left it for this follow-up.

## Solution

Delete `_expand_sp_chain()` and the `sp_call_fetcher` module. Remove the six unread parameters from `build_forward_chain()`. Update its one production caller and its two direct test callers. Correct the three stale docstring statements. The result of `build_forward_chain()` does not change for any input.

## User Stories

1. As a maintainer reading `build_forward_chain()`, I want its signature to list only inputs that change its result, so that I can see what drives the forward chain without reading the body.
2. As a maintainer reading `analyze_service.flow_chain()`, I want the forward branch to pass only arguments that `build_forward_chain()` reads, so that the call site does not imply a control it does not have.
3. As a maintainer reading `flow_chain_builder`, I want no dead private function in the module, so that I do not spend time on code that never runs.
4. As a maintainer reading the `service` package, I want no module whose only caller is dead code, so that the package listing shows only modules that take part in analysis.
5. As a maintainer reading the `flow_chain_builder` module docstring, I want it to describe the forward chain as the code builds it, so that I do not look for a recursive SP expansion that does not exist.
6. As a maintainer reading the `view_fetcher` module docstring, I want it to agree with ADR-0011, so that I do not expect a live SQL Server lookup on a cache miss.
7. As a reader of the advanced manual, I want its file tree to list only modules that exist, so that I can find each module it names.
8. As a future engineer extending the forward chain, I want no dead parameter to copy forward, so that inert surface does not spread into new code.
9. As a maintainer running the test suite after this change, I want the existing forward-chain tests to keep their assertions unchanged, so that I have direct evidence that the result did not change.
10. As a maintainer reading the forward-chain test names, I want each name to state only what the test proves, so that a name does not claim coverage that the signature already guarantees.
11. As a maintainer running mypy after this change, I want no new mypy error in the changed files, so that I know every call site matches the new signature.

## Implementation Decisions

- `flow_chain_builder`: delete `_expand_sp_chain()`. Delete the `_MAX_SP_DEPTH_HARD_CAP` constant, because only `_expand_sp_chain()` reads it. Delete the imports of `fetch_sp_definitions` and `fetch_called_sp_names`, because only `_expand_sp_chain()` uses them. Keep the imports of `extract_tables_from_definition` and `Path`, because other functions in the module use them.
- `flow_chain_builder.build_forward_chain()`: remove the parameters `sp_relations`, `root`, `database_alias`, `db_server`, `db_name`, and `max_sp_depth`. Remove the docstring paragraph about `sp_relations`. The remaining signature is `matched_files`, `anchor_method`, `graph`, and `invocations`, in that order.
- `flow_chain_builder` module docstring: remove the statement that the forward chain expands nested SP calls recursively. Remove the known-limit entry that names `sp_call_fetcher`. Keep the part of that entry about `extract_tables_from_definition` only if it is still true for the remaining code.
- `sp_call_fetcher`: delete the module.
- `analyze_service.flow_chain()`, forward branch: remove the six arguments from the `build_forward_chain()` call. Delete the local values `database_alias`, `db_server`, and `db_name`, if nothing else in the function reads them. The call to `_require_sql_execution_graph()` reads `req.db_server` directly, so it does not change.
- `view_fetcher` module docstring: replace the sentence about a live SQL Server lookup with a sentence that says the module skips a name that the cache does not hold. This agrees with ADR-0011.
- Advanced manual (`docs/進階手冊.md`): remove the `sp_call_fetcher.py` line from the file tree.
- The public request model `FlowChainRequest` does not change. See Out of Scope.

## Testing Decisions

A good test here proves that the forward chain returns the same data for the same input. A test must not check that a parameter is absent from a signature.

- **`build_forward_chain()` direct tests** (`tests/test_execution_path_integration.py`, the two forward-chain tests) are the seam. They pass `sp_relations` and `root` positionally today. Change only their call arguments: remove the `[]` / `[legacy_relation]` argument and the `tmp_path` argument. Do not change any assertion. This is different from the previous cleanup, which kept all tests unmodified. Here the tests call the changed signature, so the call must change.
- The test `test_forward_chain_without_graph_keeps_inline_sql_but_ignores_legacy_sp_relation` builds a `legacy_relation` value only to pass it as `sp_relations`. After the change, a caller cannot pass a legacy SP relation at all. The signature now guarantees "ignores legacy SP relation", so the test no longer proves it. Delete the `legacy_relation` value. Rename the test to `test_forward_chain_without_graph_keeps_inline_sql`. Do not change any assertion. Keep the `CSharpSPRelation` import, because another test in the file uses it.
- **The forward branch of `analyze_service.flow_chain()`** has no test today. All existing `flow_chain()` tests use `direction="backward"`. This ticket does not add one. Instead, run mypy on the changed files. The mypy error set must contain no new error compared to the commit before this ticket. mypy reports an unexpected keyword argument, which is the only failure this call-site edit can cause.
- No new test. The `sp_call_fetcher` module has no test to delete.

## Out of Scope

- The public request fields `FlowChainRequest.max_sp_depth` and `FlowChainRequest.db_name`. After this change, neither field changes the result of `/flow_chain`. The OpenAPI document (`docs/openapi/openapi.json`) still describes `max_sp_depth` as the depth limit for nested SP expansion. These fields are part of the public API contract that spec-rag calls. The system is still in development and has no usage evidence, so "no caller sends it" is not a valid reason to remove them. Discuss the API contract change separately, then open a ticket.
- `FlowChainRequest.db_server`. The forward branch still reads it to load the SQL Execution Graph.
- The backward direction (`build_backward_chains()`) and its parameters. This spec did not examine them.

## Further Notes

The forward branch of `analyze_service.flow_chain()` has no test coverage today. This is a pre-existing gap. This ticket relies on mypy for its call-site edit and does not close the gap. This note keeps the gap visible.

This spec comes from a grilling session after the code review of `.scratch/remove-unused-fetcher-parameters/`. That review found three unread parameters in `build_forward_chain()`. A check of the function body found six.
