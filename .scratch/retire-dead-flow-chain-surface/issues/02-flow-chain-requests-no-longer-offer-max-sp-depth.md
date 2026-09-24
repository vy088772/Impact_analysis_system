# 02 — `/flow_chain` requests no longer offer `max_sp_depth`

**What to build:** A caller of `/flow_chain` no longer sees a `max_sp_depth` field in the request model or in the OpenAPI document. The server already ignores the field, and its comment describes a nested SP expansion that does not exist. A request that still sends `max_sp_depth` succeeds, because the request model ignores an unknown field. The result of `/flow_chain` does not change. See `../spec.md` for the reason behind the removal.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `FlowChainRequest` no longer has a `max_sp_depth` field
- [x] `FlowChainRequest` still has no `model_config` that changes the handling of extra fields
- [x] `FlowChainRequest.db_name` and `FlowChainRequest.db_server` are unchanged
- [x] The committed OpenAPI document comes from the export tool, not a hand edit, and no longer lists `max_sp_depth`
- [x] The test that compares the committed OpenAPI export with the live app schema passes
- [x] The export tool's `--check` mode passes
- [x] A repo-wide search (excluding `.scratch/`) finds no reference to `max_sp_depth`
- [x] No test file changed
- [x] mypy on the changed files has no new error compared to the commit before this ticket
- [x] The full test suite has no new failure compared to the commit before this ticket

**Note:** the `.py` files in `service/` use CRLF line endings. Keep them. Tickets 01 and 03 run in parallel and touch no file that this ticket touches. Commit only this ticket's paths (`git commit --only`).

## Comments

### Implementation note (2026-09-24)

Changed paths (this ticket only):

- `service/schemas.py`: removed the `max_sp_depth` line from `FlowChainRequest`. CRLF line endings kept. No `model_config` added.
- `docs/openapi/openapi.json`: regenerated with `python -m tools.export_openapi_schema`. The only diff is the removed `max_sp_depth` property. `--check` passes.

Verification:

- `tests/test_export_openapi_schema.py`: 3 passed.
- mypy on `service/schemas.py`: no issues, before and after.
- Full suite (with `tests/test_sp_tables.py` and `tests/test_search_roles.py` ignored, because they need an ODBC driver and a live `PUR` database at import time): 16 failed, 1036 passed. The same 16 tests fail in the same tree with this ticket's two files reverted to HEAD, so this ticket adds no failure.
- Code review (Standards and Spec): no findings.
