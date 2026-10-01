# 04 — The client sends the Database host and reads "several hosts" as its own reason

**What to build:** The client of the two lookup endpoints sends the Database host (`db_server`). It also knows a new error code, `ambiguous_database`, and reports it as its own unread reason: the Database exists on several hosts, name the host. The person no longer reads that case as "not scanned". The client ships before the server (see ticket 05). An old server ignores the optional field, so the client is safe alone. The work is in the `llamaindex-spec-rag` repository.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] Both lookup requests carry `db_server` when the caller names one.
- [x] The new code maps to a new unread reason that tells the person to name the host.
- [x] The existing code for "not scanned" still maps to "not scanned".
- [x] A 409 with an unknown code still raises. It never turns into a skip.
- [x] A test at the cross-system lookup entry covers the several-hosts case and the not-scanned case.
- [x] A lookup without `db_server` keeps today's behavior.

## Note (implementation)

- Branch: `lookup-db-server-client` in `llamaindex-spec-rag` (worktree `.claude/worktrees/lookup-db-server-client`), commit `8ffe5e3`. Merged into `spec_extend_20260701` (fast-forward, local only). The worktree and the branch are removed.
- `impact_orch/rag_client.py`: new `AMBIGUOUS_DATABASE = "ambiguous_database"`. `find_by_sp` and `find_by_table` take `db_server=""` and add `db_server` to each request only when it is not empty. A lookup without it sends the same payload as before.
- `_lookup_outcomes` and `_lookup_responses` have a new flag `skip_ambiguous_database`. Only `find_by_sp` and `find_by_table` set it. A 409 with this one code becomes a skipped database with `reason=ambiguous_database`. Any other 409 code still raises. `analyze` and `flow_chain` do not change.
- `impact_orch/cross_system_lookup.py`: new `UNREAD_REASON_AMBIGUOUS_DATABASE`. The walk names these databases under their own reason. Every other skipped database stays `not_scanned`.
- `impact_orch/agent_tools.py`: plain-word label and closing text. The Evidence Gap tells the person to name the host (`db_server`). It does not say "not scanned".
- Tests: new `tests/test_lookup_db_server.py` (9 tests). It covers the request field, the 409 mapping, the unknown 409 code, the walk entry (`find_programs_by_sp` and `find_programs_by_table`) for several hosts and for not scanned, and the gap text.
- Scope decision: no caller passes `db_server` yet. `sp_lookup` and `table_lookup` do not take it. The ticket asks only that the request carries it when a caller names one. Ticket 05 (server) decides who names the host.
- Baseline in the worktree: 3 tests in `tests/test_path_selection.py` fail on a clean HEAD copy too. The sibling-path tests fail in a worktree. `mypy` shows the same 6 errors with or without this change. Full suite: 1168 passed.
- Code review: I read the diff myself. I did not run `/code-review`.

## Note (code review follow-up)

- Branch `lookup-db-server-review-fixes`, commit `5acd863`. Merged into `spec_extend_20260701`. The worktree and the branch are removed.
- Spec fix: if every declared database answers `ambiguous_database`, the lookup falls back to one request with no database name. Before, a `skipped=True` reply made the walk say "not scanned", and a 409 on that request raised (the walk then said "request failed"). Now the walk names the several-hosts reason in both cases (`cross_system_lookup.find_cached_program_matches`, `rag_client._lookup_outcomes`). New class `EveryDatabaseSeveralHostsTests` (3 tests) covers it.
- Standards fix: `cross_system_lookup._database_unreads` groups skipped databases once by reason. `agent_tools._UNREAD_DATABASES_CLOSINGS` replaces the `closing` elif chain. `rag_client._skipped_database` and `_with_db_server` replace repeated code.
- Left as is, on purpose: no caller passes `db_server` yet (ticket 05 decides who names the host). The two boolean flags `keep_partial_on_ceiling` and `skip_ambiguous_database` stay separate, to keep ticket 01 untouched. No new term in `CONTEXT.md`.
- Tests: full suite 1207 passed. The only failures are the sibling-checkout tests, which depend on the path. `mypy` shows the same 6 errors as before.

## Note (final check)

- The open question "who names the host?" is closed by ticket 09: the client sends the declared host after `ambiguous_database`.
