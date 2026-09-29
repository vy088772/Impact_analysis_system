# Retire the Dead Flow-Chain Surface

Status: ready-for-agent

## Problem Statement

The relationship chain (`/flow_chain`) still carries surface that no code reads. This surface also describes behavior that the code no longer has:

- `flow_chain_builder` contains two private functions, `_table_referenced()` and `_column_referenced()`, that have no caller. Both read SP definition text. The backward chain now takes all SQL access from the SQL Execution Graph, so no path gives SP definition text to these functions. The graph-backed path evidence migration removed their last caller.
- `build_backward_chains()` declares a `database_alias` parameter that its body never reads. `analyze_service.flow_chain()` builds a local `database_alias` value only to pass it into this parameter.
- The module docstring of `flow_chain_builder` says that column matching looks for the column name in the SP definition text. The backward chain now matches the column name against the metadata of each graph path. The match is still approximate.
- The public request model `FlowChainRequest` has a `max_sp_depth` field. Its comment says that it limits the depth of nested SP expansion. No code reads it. The previous cleanup (`.scratch/retire-dead-forward-chain-parameters/`) removed the last reader. It left the field out of scope because the field is part of the public API contract.
- The spec-rag client function for `/flow_chain` declares a `max_sp_depth` parameter and sends it in the request. Its docstring says that the forward chain expands the SPs that each SP calls. A mode 3 agent that reads this description expects a depth control that does not exist.

A caller who sets `max_sp_depth` gets the same result for every value. An engineer who reads the docstrings gets a wrong model of how the chain matches columns and nested SPs.

## Solution

Delete the two dead functions and the unread `database_alias` parameter. Remove `max_sp_depth` from `FlowChainRequest`, from the exported OpenAPI document, and from the spec-rag client. Correct the descriptions of column matching and nested SPs. The result of `/flow_chain` does not change for any request.

## User Stories

1. As a maintainer reading `flow_chain_builder`, I want no private function without a caller, so that I do not spend time on code that never runs.
2. As a maintainer reading `flow_chain_builder`, I want no function that reads SP definition text, so that the module shows that the SQL Execution Graph is the only source of SQL access facts.
3. As a maintainer reading `build_backward_chains()`, I want its signature to list only inputs that change its result, so that I can see what drives the backward chain without reading the body.
4. As a maintainer reading `analyze_service.flow_chain()`, I want the backward branch to pass only arguments that `build_backward_chains()` reads, so that the call site does not imply a control it does not have.
5. As a maintainer reading the `flow_chain_builder` module docstring, I want the column-matching limit to name the graph path metadata as the text it searches, so that I look in the right place when a column match is wrong.
6. As a maintainer reading the `flow_chain_builder` module docstring, I want it to keep the statement that column matching is approximate, so that I do not treat a column match as a guarantee.
7. As a maintainer reading the graph column-matching function, I want its docstring to explain why the match is approximate text search and not SQL parsing, so that the design reason survives the deletion of the old function that held it.
8. As a caller of `/flow_chain`, I want the request model to list only fields that change the result, so that I do not set a field that has no effect.
9. As a caller of `/flow_chain` that still sends `max_sp_depth`, I want the request to succeed after the field is removed, so that the two repositories can change in any order.
10. As a reader of the OpenAPI document, I want it to list only request fields that exist, so that the document agrees with the live app.
11. As a mode 3 agent that reads the spec-rag client description, I want it to say that the forward chain lists the SP chain that the SQL Execution Graph records, up to the server expansion limit, and where a truncated path goes, so that I do not expect a depth parameter and I find a truncated path.
12. As a maintainer of spec-rag, I want the client function for `/flow_chain` to have no parameter that the server ignores, so that no new caller copies a dead parameter forward.
13. As a maintainer running the test suite after this change, I want the existing backward-chain tests to pass without modification, so that I have direct evidence that the result did not change.
14. As a maintainer running the spec-rag test suite after this change, I want the existing flow-chain tests to pass without modification, so that I know that the multi-database query and merge did not change.
15. As a maintainer running mypy in each repository after this change, I want no new mypy error, so that I know every call site matches the new signatures.
16. As a future engineer who considers a depth limit for the SP chain, I want this spec to record why the field was removed and why the existing expansion limit stays, so that I do not confuse the removed caller field with the server expansion limit.

## Implementation Decisions

- `flow_chain_builder`: delete `_table_referenced()` and `_column_referenced()`. Keep every import that another function in the module still uses.
- `flow_chain_builder`, graph column-matching function (`_graph_access_matches_column()`): replace its one-line docstring with the design reason from `_column_referenced()`, adapted to graph metadata. The reason is: exact column matching needs a parse of the SQL clauses. A parse costs much and breaks when the T-SQL syntax varies. Thus the function searches for the column name as a whole word in the path metadata (`written_columns`, `conditions`, `reads`, `writes`). A caller must tell the user that a match is approximate. The docstring must not refer to "the existing filter", because that filter is the deleted function.
- `flow_chain_builder` module docstring: rewrite the known-limit entry about column matching. The entry names the graph path metadata as the text that the match searches. The entry keeps the statement that the match is approximate text matching, not a structured guarantee, and can give a false match.
- `build_backward_chains()`: remove the `database_alias` parameter.
- `analyze_service.flow_chain()`: remove the `database_alias` argument from the `build_backward_chains()` call. Delete the local `database_alias` value if nothing else in the function reads it.
- `FlowChainRequest`: remove the `max_sp_depth` field. Do not add a `model_config` that changes the handling of extra fields. The model uses the Pydantic default, which ignores an unknown field. Thus a request that still sends `max_sp_depth` succeeds, and the server uses no value from it.
- `FlowChainRequest.db_name` does not change. `DerivedExecutionEvidenceScope` reads it as part of the derived evidence store key, so it changes which stored evidence the request uses.
- OpenAPI document: regenerate it with the export tool. Do not edit it by hand.
- spec-rag client function for `/flow_chain`: remove the `max_sp_depth` parameter. Remove `max_sp_depth` from the request payload. Rewrite the forward-direction sentence of its docstring: the forward chain goes from the anchor method along the method call chain, lists the SP chain that the SQL Execution Graph records (nested calls included, up to the server expansion limit), and collects the tables of each SP. The docstring tells the agent that it has no depth parameter and that a truncated path goes to `diagnostics`. Keep the backward-direction sentence that calls column matching approximate. This change is in the `llamaindex-spec-rag` repository, so its commit goes there.
- The two repositories can change in any order. Server first: the old client sends a field that the server ignores. Client first: the server applies the default of a field that it does not read.
- No ADR. The field has no effect now, and a later spec can add a field back without a migration. This spec records the decision and its reason. See Further Notes.

## Testing Decisions

A good test here proves that `/flow_chain` returns the same data for the same request. A test must not check that a function, a parameter, or a field is absent.

- **Backward chain through `analyze_service.flow_chain()`** is the seam for the `database_alias` removal. The backward flow-chain tests in the graph reverse-lookup test module pass `database`, so their requests go through the argument that this spec deletes. Do not change these tests. They must pass without modification.
- **OpenAPI export check** is the seam for the `max_sp_depth` removal. The test that compares the committed export with the live app schema fails until the export is regenerated. After regeneration, it must pass. The export tool's `--check` mode must also pass.
- **spec-rag flow-chain tests** (the declared-databases test module) are the seam for the client change. They stub the HTTP post and see each request payload. Do not change these tests. They must pass without modification.
- The deletion of `_table_referenced()` and `_column_referenced()` and the docstring edits change no behavior. A repo-wide search (excluding `.scratch/`) must find no reference to the two deleted functions.
- mypy in each repository: the error set of the changed files must contain no new error compared to the commit before the change. In spec-rag, mypy is the only check that finds a caller that still passes `max_sp_depth`.
- The full test suite of each repository must have no new failure compared to the commit before the change.
- No new test. A schema test that checks that an old payload with `max_sp_depth` still validates would protect only the transition period, after which spec-rag no longer sends the field.

## Out of Scope

- `FlowChainRequest.db_name` and `FlowChainRequest.db_server`. The request still reads both.
- The accuracy of graph column matching. This spec corrects only its description.
- Any other endpoint's request model.
- Other unread parameters in `flow_chain_builder` that this spec did not examine.

## Further Notes

**Why remove `max_sp_depth` and not give it an effect.** The removal does not rest on "no caller uses the field". The system is still in development and has no usage evidence, so that argument is not valid. The removal rests on two facts: the server ignores this caller field, and its description claims a depth control that the caller does not have. The server has a separate expansion limit, `max_call_depth` with the value 5, that no caller can set. The expansion limit stays, because the server reports each truncated path in `diagnostics` as `call_expansion_truncated`, so no fact disappears without a report. A change to the expansion limit needs its own spec.

**Why the removal is safe for an old client.** `FlowChainRequest` has no `model_config`, so Pydantic ignores an unknown field. An old spec-rag client that sends `max_sp_depth` still gets a valid request.

This spec comes from a grilling session after ticket 01 of `.scratch/retire-dead-forward-chain-parameters/`. The code review of that ticket found the two dead functions. The grilling session also found the unread `database_alias` parameter.
