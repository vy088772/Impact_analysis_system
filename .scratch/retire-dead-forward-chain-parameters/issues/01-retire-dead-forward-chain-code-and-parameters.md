# 01 — Retire dead forward-chain code and parameters

**What to build:** Delete `service/flow_chain_builder._expand_sp_chain()` and the `service/sp_call_fetcher.py` module. Remove the six unread parameters from `build_forward_chain()`. Update the one production caller, the two direct test callers, and three stale docstring statements. See `../spec.md` for the reason behind each step.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `service/flow_chain_builder.py` no longer contains `_expand_sp_chain()` or `_MAX_SP_DEPTH_HARD_CAP`
- [ ] `service/flow_chain_builder.py` no longer imports `fetch_sp_definitions` or `fetch_called_sp_names`; it still imports `extract_tables_from_definition` and `Path`
- [ ] `service/sp_call_fetcher.py` no longer exists
- [ ] `build_forward_chain()` declares only `matched_files`, `anchor_method`, `graph`, and `invocations`, and its docstring no longer has the `sp_relations` paragraph
- [ ] The `flow_chain_builder.py` module docstring no longer says the forward chain expands nested SP calls, and no longer names `sp_call_fetcher`
- [ ] `service/analyze_service.flow_chain()` passes only the four remaining arguments to `build_forward_chain()`, and no longer has unused `database_alias` / `db_server` / `db_name` locals
- [ ] The `service/view_fetcher.py` module docstring says that a name the cache does not hold is skipped (ADR-0011), not looked up live
- [ ] `docs/進階手冊.md` no longer lists `sp_call_fetcher.py`
- [ ] In `tests/test_execution_path_integration.py`, the two `build_forward_chain()` calls no longer pass the `sp_relations` and `root` arguments; no assertion changed
- [ ] `test_forward_chain_without_graph_keeps_inline_sql_but_ignores_legacy_sp_relation` is renamed to `test_forward_chain_without_graph_keeps_inline_sql`, and its `legacy_relation` value is deleted
- [ ] mypy on the changed `.py` files reports no new error compared to the commit before this ticket
- [ ] The full test suite has no new failure compared to the commit before this ticket
- [ ] `FlowChainRequest` and `docs/openapi/openapi.json` are unchanged (out of scope)

**Note:** the `.py` files in `service/` use CRLF line endings. Keep them.

## Comments
