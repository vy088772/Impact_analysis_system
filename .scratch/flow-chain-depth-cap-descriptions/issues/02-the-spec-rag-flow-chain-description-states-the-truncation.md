# 02 — The spec-rag flow-chain description states the truncation

**What to build:** In the `llamaindex-spec-rag` repository, the docstring of the client function for `/flow_chain` tells a mode 3 agent the truth about the forward chain. A caller has no depth parameter. The server stops the expansion at a nesting that is too deep or at a stored-procedure call cycle. The truncated path goes to `diagnostics` and not to `stored_procedures` or `tables`. The return-value line lists `diagnostics`. The behavior of the function does not change. See `../spec.md` (in the `Impact_analysis_system` repository) for the agreed text and the reason.

**Blocked by:** 01 — A test proves where a truncated forward path goes.

**Status:** done

- [x] The forward-direction paragraph no longer says "沒有深度控制：圖上記錄了幾層就回幾層"
- [x] The forward-direction paragraph contains the agreed text from `../spec.md`, Implementation Decisions
- [x] The docstring names the reasons `call_expansion_truncated` and `stored_procedure_call_cycle`
- [x] The docstring does not state the numeric expansion limit
- [x] The forward-direction sentence about the method call chain, the SP chain, and the tables of each SP stays
- [x] The backward-direction sentence still says that column matching is approximate and not a guarantee
- [x] The return-value line lists `diagnostics`. The other listed fields do not change
- [x] Only the docstring changed. The function signature and body did not change
- [x] The declared-databases flow-chain tests pass without modification
- [x] No test file changed
- [x] mypy on the changed file, run with the project virtual environment, has no new error compared to the commit before this ticket
- [x] The full spec-rag test suite has no new failure compared to the commit before this ticket

**Note:** do the work and the commit in the `llamaindex-spec-rag` repository, not in `Impact_analysis_system`. The client module uses LF line endings. Keep them. Mark this ticket done in this file, in the `Impact_analysis_system` repository. If ticket 01 recorded a different behavior, write the docstring to match the recorded behavior, not the agreed text.

## Comments

### 2026-09-29 — implemented

- Commit `49326d3` in `llamaindex-spec-rag`. It changes only the docstring of `flow_chain` in `impact_orch/rag_client.py` (4 lines added, 2 lines removed). The file keeps LF line endings.
- The forward-direction paragraph now holds the agreed text from `../spec.md` word for word. The return-value line is `{direction, forward_chain, backward_chains, diagnostics, skipped, source_root}`. The order follows the dict that the function returns.
- Ticket 01 recorded the agreed behavior, so the docstring uses the agreed text. A code check confirms the claims. The function body merges the top-level `diagnostics` (`rag_client.py`, the `return` of `flow_chain`). `_merge_forward_chains` also keeps `forward_chain.diagnostics`. Thus the sentence is true for both fields.
- mypy on `impact_orch/rag_client.py` with `.venv`: 6 errors before and after, the same messages.
- `tests/test_flow_chain_declared_databases.py`: 7 passed, no change to the file.
- Full suite: 2 failed, 1209 passed, before and after, with the same 2 failures (`test_path_evidence_wiring.py::test_clients_route_the_sql_cache_by_database_name_not_system_id` and `test_source_resolver_databases.py::test_the_shipped_catalog_declares_databases_as_full_identities`).
- Code review: the Spec axis found no issue. The Standards axis found no hard violation and gave three judgement calls. None of them caused a change:
  - The file uses "server" for the SQL Server host, and uses `Impact 端` for the remote service. The agreed text says "server". The text stays as agreed. A later docstring change can use `Impact 端`, but it must first change the spec text.
  - Two `diagnostics` fields exist (top level and `forward_chain`). The truncated path is in both, so the sentence is true for each reading.
  - The return-value line is 90 display columns, and the local wrap is about 80. No lint rule enforces a limit.
- Not covered by a test: the `stored_procedure_call_cycle` route. Ticket 01 tested only the truncation case. A code read confirms that the cycle takes the same route.
