# 01 — A reverse lookup spends from the run request budget

**What to build:** A stored-procedure lookup and a table lookup count against the one request budget of the agent run. When the budget is spent, the lookup lists each System it did not read, with the reason "request ceiling reached". The run does not stop and does not raise. The person sees which Systems have no answer and why. The work is in the `llamaindex-spec-rag` repository.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] Both lookups receive the budget of the agent run and pass it to the shared cross-system lookup. Neither creates its own budget.
- [x] A test at the cross-system lookup entry shows that a spent budget puts each unread System in `unread_systems` with the new reason.
- [x] The run continues after the ceiling is reached, and the Systems already read keep their answers.
- [x] A stored-procedure lookup and a table lookup in the same run draw from the same budget.
- [x] The report and the agent answer name the new reason in plain words.
- [x] An existing reason ("request failed", "not scanned") keeps its meaning.

## Note (implementation)

- Branch: `lookup-01-budget` in `llamaindex-spec-rag` (worktree `.claude/worktrees/lookup-01-budget`), commit `caf1368`. Not merged yet.
- `impact_orch/cross_system_lookup.py`: new `UNREAD_REASON_REQUEST_CEILING = "request_ceiling_reached"`. The walk checks `request_budget.exhausted` before each System and lists the System as unread without asking. A request that raises with `code == rag_client.REQUEST_CEILING_CODE` gets the same reason. The walk continues, so Systems already read keep their answers. The locate request already took the budget.
- `impact_orch/rag_client.py`: `REQUEST_CEILING_CODE`; `_send_with_retry` sets it on the ceiling error.
- `impact_orch/sp_lookup.py`, `impact_orch/table_lookup.py`: all three lookup functions take `request_budget` and pass it to `find_by_sp` / `find_by_table` and to the shared walk.
- `impact_orch/scope_policy.py` (CRLF file; keep it): `scoped_lookup_recording` passes `state.request_budget` to the lookup when the state has one. This covers all six call sites (agent tools and pre-agent lookups) with no change to them. `_probe_unmarked_candidate` with `state=None` keeps its own budget.
- `impact_orch/agent_tools.py`: plain-word label for the new reason in `_UNREAD_SYSTEM_REASON_LABELS`. The label reaches the Evidence Gap, the Impact Coverage Scope section, and the agent answer.
- Tests: new `tests/test_lookup_request_budget.py` (8 tests, includes the walk-entry test). `tests/test_architecture_modules.py`: expected calls now include `request_budget`.
- Worktree baseline: `.env` is untracked; copy it from the main checkout. 3 tests in `tests/test_path_selection.py` and the sibling-path tests fail with or without this change. `mypy impact_orch` keeps 81 errors, same as before.

## Note (code review follow-up)

- Second commit on `lookup-01-budget` (see `git log`). Fixes from `/code-review`:
- `rag_client._lookup_outcomes` has a new flag `keep_partial_on_ceiling`. Only `_lookup_responses` (the lookup path) sets it. A budget that ends after at least one database was read keeps those matches. The remaining databases enter `databases_skipped` with `reason == REQUEST_CEILING_CODE`. Analyze keeps its old behaviour. A ceiling before any read still raises and the walk names the whole System.
- `cross_system_lookup.find_cached_program_matches` splits `databases_skipped` by reason: a ceiling database gives `UnreadSystem(reason=request_ceiling_reached, databases=...)`; any other gives `not_scanned`, as before.
- `agent_tools.record_unread_systems`: a partly read System under the ceiling reason says "因上限而未讀取的資料庫 ... 已讀取的資料庫仍納入"; it no longer says "尚未掃描".
- One constant: `UNREAD_REASON_REQUEST_CEILING = rag_client.REQUEST_CEILING_CODE`. Duplicate `UnreadSystem(...)` append is one local variable. Comment and docstring of the reason values rewritten. Import order and long test lines fixed; inline test import moved to the top.
- New tests: partial read, ceiling before any read, walk split, coverage text end to end (15 tests in `tests/test_lookup_request_budget.py`).
- Not changed on purpose: (1) `LookupContext` for `request_budget` + `locate_cache` — only two items, and many test doubles patch the exact keyword names. (2) `getattr(state, "request_budget", None)` in `scope_policy` — `state` is duck-typed, and the fake states in tests have no budget. (3) `record_unread_systems` dedupes by `system_id`, first reason wins — this is the rule of ticket 02. (4) Patching private `_locate_object` in tests — the same seam other tests use.
- Baseline unchanged: 3 `test_path_selection` tests and the sibling-path tests fail in a worktree with or without this work; `mypy impact_orch` keeps 81 errors.

