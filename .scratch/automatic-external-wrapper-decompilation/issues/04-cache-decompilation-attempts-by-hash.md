# 04 — Cache decompilation attempts by DLL hash

**What to build:** A decompilation attempt's outcome (complete, incomplete with reasons, or not attempted) is cached keyed by the DLL's SHA-256 hash, so an unchanged DLL is not re-decompiled on every subsequent refresh. The cache is a separate concern from the existing C# source-scan cache, and is invalidated only when the DLL's hash changes or a maintainer explicitly requests a re-run.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] A second decompilation request for a DLL whose hash matches a cached attempt does not re-invoke the decompiler, and returns the cached outcome (complete/incomplete/not-attempted)
- [ ] A DLL whose hash differs from any cached entry triggers a fresh decompilation attempt
- [ ] A cached incomplete/failed attempt is not retried automatically on subsequent refreshes of an unchanged DLL, only on hash change or an explicit re-run request
- [ ] The cache is keyed and stored independently of the existing C# source-scan cache (no shared cache entries or invalidation triggers)
- [ ] Tests verify: cache hit avoids re-decompilation (e.g. via a call-count assertion on the decompile step), cache miss on a changed hash triggers a fresh attempt, and an explicit re-run request bypasses a cached failure
