# 04 — Cache decompilation attempts by DLL hash

**What to build:** A decompilation attempt's outcome (complete, incomplete with reasons, or not attempted) is cached keyed by the DLL's SHA-256 hash, so an unchanged DLL is not re-decompiled on every subsequent refresh. The cache is a separate concern from the existing C# source-scan cache, and is invalidated only when the DLL's hash changes or a maintainer explicitly requests a re-run.

**Blocked by:** 03.

**Status:** resolved

- [x] A second decompilation request for a DLL whose hash matches a cached attempt does not re-invoke the decompiler, and returns the cached outcome (complete/incomplete/not-attempted)
- [x] A DLL whose hash differs from any cached entry triggers a fresh decompilation attempt
- [x] A cached incomplete/failed attempt is not retried automatically on subsequent refreshes of an unchanged DLL, only on hash change or an explicit re-run request
- [x] The cache is keyed and stored independently of the existing C# source-scan cache (no shared cache entries or invalidation triggers)
- [x] Tests verify: cache hit avoids re-decompilation (via the public attempt metadata), cache miss on a changed hash triggers a fresh attempt, and an explicit re-run request bypasses a cached failure

## Answer

Implemented hash-keyed decompilation attempt caching at both `StaticAnalyzerHost.decompile_wrapper()` and the direct `decompile-wrapper` console boundary.

- Python and .NET host caches persist independently under `data/decompilation_cache` and its `host/` subdirectory, with one cache document per DLL SHA-256 identity and receiver type entries inside the document.
- Complete and incomplete outcomes are reused without decompilation; changed DLL bytes select a new hash entry; `rerun=True` or `--rerun` bypasses and replaces a cached failure.
- Responses expose `attempt_outcome`, `cache_status`, and `decompilation_attempt.attempted` for refresh/reporting callers. A missing/untraceable DLL has no hash to key, so it remains `not_attempted`/`not_applicable` rather than creating a guessed cache entry.
- Tests cover complete and incomplete cache hits, changed hashes, explicit reruns, warm host-cache fallback, direct CLI behavior, and source-cache separation.

Validation:

- `dotnet build tools/StaticAnalyzerHost/StaticAnalyzerHost.csproj --nologo` passed.
- Focused wrapper/host/preflight tests: 26 passed; wrapper tests after final review fix: 9 passed.
- Applicable full suite: 342 passed, 2 pre-existing failures (Windows-only MVC path and legacy graph-output assertion).
- Two live-DB modules could not collect because this machine lacks `ODBC Driver 17 for SQL Server`.
