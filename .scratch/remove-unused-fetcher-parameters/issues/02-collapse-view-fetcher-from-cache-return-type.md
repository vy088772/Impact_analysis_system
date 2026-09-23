# 02 — Collapse view_fetcher._from_cache's return type from tuple to list

**What to build:** `service/view_fetcher._from_cache()` returns `(found, missing)`, but `missing` is hardcoded empty on every path — nothing in the function body ever appends to it (a name that isn't a cached View is `continue`d, not recorded as missing). Change its return type to a plain `List[dict]`, update the docstring's stated return shape, and update `fetch_view_definitions()`'s one call site (`found, _ = self._from_cache(...)` → `found = self._from_cache(...)`).

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `service/view_fetcher._from_cache()` returns `List[dict]` instead of a tuple, and its docstring reflects the new return shape
- [x] `fetch_view_definitions()` is updated to `found = self._from_cache(...)` (no tuple unpacking)
- [x] Full test suite still passes (no existing test covers this module directly)

## Comments

**Implementation note (2026-09-23):**

- Changed file: `service/view_fetcher.py` only. `_from_cache()` now returns `List[dict]`; its three `return` paths return one list. `fetch_view_definitions()` now uses `found = _from_cache(...)`.
- `_from_cache()` had no docstring before this change. The implementer added a one-line docstring that states the new return shape.
- The spec and this ticket write `self._from_cache(...)`. `_from_cache` is a module-level function, not a method. The call site has no `self.`.
- The file uses CRLF line endings. The change keeps them.
- Test suite: 1036 passed, 16 failed. `tests/test_search_roles.py` and `tests/test_sp_tables.py` fail at collection because they need a live SQL Server. A clean HEAD worktree gives the same failures on the same test files. The only differences come from local data under `data/repos/` that git ignores. No failing test goes through `view_fetcher`.
- mypy reports no error in `service/view_fetcher.py`.
