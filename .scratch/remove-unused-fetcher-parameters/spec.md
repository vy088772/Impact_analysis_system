# Remove Unused Parameters in sp_fetcher and view_fetcher

Status: ready-for-agent

## Problem Statement

Two interfaces promise a choice their implementation no longer makes, or never made:

- `service/sp_fetcher.fetch_sp_definitions()` accepts a `db_name` parameter. Its own docstring says the function does not use it ("db_name 參數保留供呼叫端相容，本函式不使用它"). One production caller (`service/analyze_service.py`) still passes it, which means an engineer reading either the signature or the call site has to open the function body to learn the value is discarded.
- `service/view_fetcher._from_cache()` returns a two-element tuple, `(found, missing)`. Every code path that returns from this function supplies an empty list for the second element — a name that isn't a cached View is simply skipped (`continue`), never appended anywhere. The public wrapper, `fetch_view_definitions()`, unpacks and discards that second element (`found, _ = self._from_cache(...)`). The tuple shape promises "here's what's missing," but nothing in the function can ever populate it.

An engineer reading either module has no way to tell, from the signature alone, that these bits of surface are already dead.

## Solution

Delete the `db_name` parameter from `fetch_sp_definitions()`, and update its one caller that passes it. Collapse `_from_cache()`'s return type from `tuple[List[dict], List[str]]` to `List[dict]`, and update `fetch_view_definitions()`'s one call site to match. No behavior change for any caller — both are pure interface trims of already-inert surface.

## User Stories

1. As a maintainer reading `service/sp_fetcher.py`, I want `fetch_sp_definitions()`'s signature to list only parameters the function actually reads, so that I don't have to open the docstring to learn one of them is inert.
2. As a maintainer reading the call site in `service/analyze_service.py`, I want it to pass only arguments `fetch_sp_definitions()` actually uses, so that the call site doesn't imply a control it doesn't have.
3. As a maintainer reading `service/view_fetcher.py`, I want `_from_cache()`'s return type to describe what the function can actually produce, so that a tuple shape doesn't promise a "missing names" list that never gets populated.
4. As a maintainer reading `fetch_view_definitions()`, I want its one call site to reflect the trimmed return shape, so that a discarded `_` doesn't linger as a hint something is being thrown away.
5. As a future engineer extending `sp_fetcher.py` or `view_fetcher.py`, I want no dead parameter or dead tuple slot to copy forward as a pattern into new code, so that inert surface doesn't propagate.
6. As a maintainer running the test suite after this change, I want every existing test for `fetch_sp_definitions()` and `fetch_view_definitions()` to keep passing unmodified, so that I have direct evidence neither removed parameter carried real behavior.

## Implementation Decisions

- `service/sp_fetcher.py`: remove the `db_name: Optional[str] = None` parameter from `fetch_sp_definitions()`. Remove the corresponding docstring line noting it's unused. Leave `db_server` untouched — it's a different, actually-used parameter.
- `service/analyze_service.py`: at the one call site that passes `db_name=req.db_name or None` to `fetch_sp_definitions()`, remove that keyword argument.
- `service/view_fetcher.py`: change `_from_cache()`'s return type from `tuple[List[dict], List[str]]` to `List[dict]`. Return the `found` list directly instead of `(found, [])`. Update the docstring's stated return shape.
- `service/view_fetcher.py`: in `fetch_view_definitions()`, change `found, _ = self._from_cache(...)` to `found = self._from_cache(...)`.
- Do not touch `service/sp_fetcher.py`'s own `_from_cache()` — its second tuple element (`missing`) is genuinely populated with real cache-miss names, a different situation from `view_fetcher.py`'s always-empty one. Out of scope here.

## Testing Decisions

A good test here proves the function still returns the same data for the same callers, not that a specific parameter is absent from the signature. No new test seam is needed — both functions already have direct unit-test coverage at the right level.

- **`tests/test_sp_fetcher.py`** and **`tests/test_formal_output_migration.py`** (the existing direct calls to `sp_fetcher.fetch_sp_definitions()`) are the seam for the `db_name` removal. Neither test passes `db_name` today; confirm both keep passing unmodified after the parameter is removed from the signature.
- `service/view_fetcher.py` currently has no direct unit test, and no integration test (`/analyze` with `include_sp_defs=True`) exercises a View-shaped cached name either — confirmed by repo-wide search. This change has no existing seam to update, and adding new coverage is out of scope for this ticket (see Further Notes).

## Out of Scope

- `service/dependency_fetcher.py`'s `database_alias` parameter. `.scratch/retire-legacy-dependency-dictionary/` already carries an unimplemented `ready-for-agent` ticket (issue 03) that deletes the whole module, a superset of trimming this one parameter. Do not duplicate that work here.
- `service/schemas.py`'s `include_execution_paths` field. It still gates real behavior in `service/analyze_service.py` (`if req.include_execution_paths and matched_files:`) and has a dedicated regression test (`tests/test_execution_path_integration.py`) proving the `False` branch skips path construction. It was proposed for removal in the same original cleanup pass, checked against the code, and found not to be a dead parameter.
- `service/sp_fetcher.py`'s own `_from_cache()` second tuple element (`missing`) — it carries real data; only its caller discards it, a different and lower-priority situation than `view_fetcher.py`'s always-empty case.

## Further Notes

`service/view_fetcher.py` has zero direct or indirect test coverage today. That's a pre-existing gap, not something this ticket introduces or is responsible for closing — flagging it here so it stays visible rather than being silently carried forward.

This spec was produced from a grilling session that checked six candidate "nobody passes this parameter" sites against the actual production code and tests before accepting any of them. One candidate (`include_execution_paths`) failed that check and was dropped; see Out of Scope.
