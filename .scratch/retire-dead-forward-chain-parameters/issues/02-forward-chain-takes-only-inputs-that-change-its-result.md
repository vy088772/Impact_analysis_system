# 02 — The forward chain takes only inputs that change its result

**What to build:** `build_forward_chain()` accepts only the four inputs that its body reads: the matched files, the anchor method, the SQL Execution Graph, and the invocations. The forward branch of `/flow_chain` passes only those four. An engineer who reads the signature or the call site sees exactly what drives the forward chain. The result of the forward chain does not change for any input, and the public request model `FlowChainRequest` does not change. See `../spec.md` for the reason behind each step.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `build_forward_chain()` no longer declares `sp_relations`, `root`, `database_alias`, `db_server`, `db_name`, or `max_sp_depth`
- [ ] The `build_forward_chain()` docstring no longer has the paragraph about `sp_relations`
- [ ] The forward branch of `analyze_service.flow_chain()` passes only the four remaining inputs, and has no local value that only existed to feed a removed parameter
- [ ] The two forward-chain tests that call `build_forward_chain()` directly pass without the removed arguments, and no assertion changed
- [ ] The forward-chain test that proved "ignores legacy SP relation" is renamed to `test_forward_chain_without_graph_keeps_inline_sql`, and its legacy-relation value is deleted
- [ ] mypy on the changed `.py` files reports no new error compared to the commit before this ticket
- [ ] The full test suite has no new failure compared to the commit before this ticket
- [ ] `FlowChainRequest` and the OpenAPI document are unchanged (out of scope)

**Note:** ticket 01 also edits `flow_chain_builder`. The two tickets do not depend on each other. If two agents work on them at the same time, expect a merge conflict in that module.

**Note:** the `.py` files in `service/` use CRLF line endings. Keep them.

## Comments
