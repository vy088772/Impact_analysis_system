# 03 — The spec-rag flow-chain client sends only live fields and describes the graph SP chain

**What to build:** In the `llamaindex-spec-rag` repository, the client function for `/flow_chain` no longer accepts or sends `max_sp_depth`. Its docstring tells a mode 3 agent that the forward chain goes from the anchor method along the method call chain, lists the SP chain that the SQL Execution Graph records (nested calls included), and collects the tables of each SP. The agent no longer expects a depth control. The multi-database query and merge do not change. See `../spec.md` (in the `Impact_analysis_system` repository) for the reason behind the removal.

**Blocked by:** None — can start immediately. Ticket 02 removes the same field on the server. The two can land in any order.

**Status:** done

- [x] The spec-rag client function for `/flow_chain` no longer has a `max_sp_depth` parameter
- [x] The request payload that the function sends no longer contains `max_sp_depth`
- [x] The payload still contains `db_name` and `db_server`
- [x] The forward-direction sentence of the docstring describes the SP chain from the SQL Execution Graph, nested calls included, and no longer says that the chain expands the SPs that each SP calls
- [x] The backward-direction sentence of the docstring still says that column matching is approximate and not a guarantee
- [x] A repo-wide search in spec-rag (excluding `.scratch/`) finds no reference to `max_sp_depth`
- [x] The declared-databases flow-chain tests pass without modification
- [x] No test file changed
- [x] mypy on the changed files has no new error compared to the commit before this ticket
- [x] The full spec-rag test suite has no new failure compared to the commit before this ticket

**Note:** do the work and the commit in the `llamaindex-spec-rag` repository, not in `Impact_analysis_system`. The client module uses LF line endings. Keep them. Mark this ticket done in this file, in the `Impact_analysis_system` repository.

## Comments

### 2026-09-24 — implemented (llamaindex-spec-rag commit 5e6873b)

- Changed file: `impact_orch/rag_client.py` only (`flow_chain()`). The commit removed the `max_sp_depth` parameter and the `max_sp_depth` payload key. It also rewrote the forward-direction docstring sentence. LF line endings stay.
- The docstring also says "沒有深度控制：圖上記錄了幾層就回幾層". The spec review flagged this as outside the ticket text. It stays because the ticket says the agent no longer expects a depth control (user story 11).
- `tests/test_flow_chain_declared_databases.py`: 7 passed. No test file changed.
- mypy `impact_orch/rag_client.py`: 9 errors before and after. The only difference is the line numbers, one lower.
- Full suite: 2 failed, 1164 passed before and after. The two failures exist on c1425a3 and do not relate to this ticket: `test_path_evidence_wiring.py::test_clients_route_the_sql_cache_by_database_name_not_system_id` and `test_source_resolver_databases.py::test_the_shipped_catalog_declares_databases_as_full_identities`.
- Repo-wide search for `max_sp_depth` (excluding `.scratch/`, `.venv/`): zero hits.

**2026-09-29:** `../../flow-chain-depth-cap-descriptions/spec.md` records the correction of the docstring sentence "沒有深度控制：圖上記錄了幾層就回幾層", because the server has an expansion limit.
