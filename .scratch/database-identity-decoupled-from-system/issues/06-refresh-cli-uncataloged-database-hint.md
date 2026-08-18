# 06 — `refresh_cli` Flags Uncataloged Databases With an Actionable Hint

**Repo:** `llamaindex-spec-rag`
**Spec:** `Impact_analysis_system/.scratch/database-identity-decoupled-from-system/spec.md`
**ADR:** `docs/adr/0002-new-database-scanning-is-explicit.md`

**What to build:** This is the original ask that started this whole effort: `refresh_cli`'s unresolved summary tells an analyst "this database is real, it just hasn't been scanned yet" instead of lumping it in with genuine static-analysis gaps — and tells them exactly what command fixes it.

**Blocked by:** 03 (the `not_in_resolved_catalog` reason must actually be reachable and correct), 05 (the suggested command must actually work as suggested)

**Status:** ready-for-agent

- [ ] `refresh_cli`'s unresolved-results summary buckets `not_in_resolved_catalog` results separately from other unresolved reasons.
- [ ] For each distinct uncataloged database, it prints "其中 N 筆為「資料庫未建檔」，refresh_sql_cli 建立 `<database>`" — deduplicated once per database regardless of how many invocations hit it (verified with a case where 3+ calls hit the same uncataloged database and only one hint line appears, with N reflecting the true call count).
- [ ] Running `refresh_cli STC` today's way (before any of tickets 01/02/03/04/05 land) is unaffected for reasons other than `not_in_resolved_catalog`.
- [ ] Nothing in `refresh_cli` triggers `refresh_sql_cli` or any live SQL scan automatically upon discovering an uncataloged database — the hint is informational only.
- [ ] `tests/test_refresh_cli.py` gains cases for: the bucketed message text, deduplication across multiple invocations of the same database, and confirmation that no scan is triggered as a side effect of printing the hint.
