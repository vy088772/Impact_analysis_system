# 02 — The forward chain takes only inputs that change its result

**What to build:** `build_forward_chain()` accepts only the four inputs that its body reads: the matched files, the anchor method, the SQL Execution Graph, and the invocations. The forward branch of `/flow_chain` passes only those four. An engineer who reads the signature or the call site sees exactly what drives the forward chain. The result of the forward chain does not change for any input, and the public request model `FlowChainRequest` does not change. See `../spec.md` for the reason behind each step.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `build_forward_chain()` no longer declares `sp_relations`, `root`, `database_alias`, `db_server`, `db_name`, or `max_sp_depth`
- [x] The `build_forward_chain()` docstring no longer has the paragraph about `sp_relations`
- [x] The forward branch of `analyze_service.flow_chain()` passes only the four remaining inputs, and has no local value that only existed to feed a removed parameter
- [x] The two forward-chain tests that call `build_forward_chain()` directly pass without the removed arguments, and no assertion changed
- [x] The forward-chain test that proved "ignores legacy SP relation" is renamed to `test_forward_chain_without_graph_keeps_inline_sql`, and its legacy-relation value is deleted
- [x] mypy on the changed `.py` files reports no new error compared to the commit before this ticket
- [x] The full test suite has no new failure compared to the commit before this ticket
- [x] `FlowChainRequest` and the OpenAPI document are unchanged (out of scope)

**Note:** ticket 01 also edits `flow_chain_builder`. The two tickets do not depend on each other. If two agents work on them at the same time, expect a merge conflict in that module.

**Note:** the `.py` files in `service/` use CRLF line endings. Keep them.

## Comments

### 2026-09-24 — implementation notes

**Files changed (and nothing else):**

- `service/flow_chain_builder.py` — removed the parameters `sp_relations`, `root`, `database_alias`, `db_server`, `db_name`, and `max_sp_depth` from `build_forward_chain()`. The signature is now `matched_files`, `anchor_method`, `graph`, `invocations`. Removed the docstring paragraph that starts with "sp_relations：保留這個參數是為了相容舊呼叫端". No other part of this module changed in this ticket.
- `service/analyze_service.py` — in `flow_chain()`, deleted the local values `db_server` and `db_name`. Kept `database_alias`, because the backward branch passes it to `build_backward_chains()`. In the forward branch, the `build_forward_chain()` call now passes `matched_files`, `req.anchor_method`, `graph=execution_graph`, and `invocations=rated_invocations`.
- `tests/test_execution_path_integration.py` — in the two forward-chain tests, removed the `[]` / `[legacy_relation]` argument and the `tmp_path` argument from the `build_forward_chain()` call. Renamed `test_forward_chain_without_graph_keeps_inline_sql_but_ignores_legacy_sp_relation` to `test_forward_chain_without_graph_keeps_inline_sql`. Deleted its `legacy_relation` value. No assertion changed. The `CSharpSPRelation` import stays, because another test uses it.

**Parallel work with ticket 01:** ticket 01 edits `flow_chain_builder.py` in the same working tree at the same time. This ticket's commit holds only the hunks listed above. The commit does not include ticket 01's edits (the `_expand_sp_chain()` deletion, the module docstring, the imports, `view_fetcher.py`, `sp_call_fetcher.py`, and the advanced manual).

**Line endings:** the three `.py` files use CRLF. The committed diff keeps CRLF.

**Verification:**

- `tests/test_execution_path_integration.py` — 14 passed.
- mypy on the three changed `.py` files: no new error. Two `no-redef` errors in `analyze_service.py` moved by two lines. They are the same errors as before.
- Full suite (with `tests/test_search_roles.py` and `tests/test_sp_tables.py` ignored, because both fail at collection with `KeyError: 'PUR'` before and after this change): 16 failed, 1036 passed. The list of failed tests is identical to the list before this change.
- `FlowChainRequest` and `docs/openapi/openapi.json` did not change.
