# 02 — Report CREATE TABLE for a temp table

**What to build:** A decision on a report of `CREATE TABLE #name` by the analyzer. With this fact, a module that creates its temp table with `CREATE TABLE` and fills it with `INSERT` gets Temp Table Shadowing, as a `SELECT ... INTO #name` does now (ADR-0043). Today such a module still receives the base tables of the caller's `#name`.

The cost: an analyzer change, a new SQL cache refresh for every Database, and a new graph fact. ADR-0036 rejected this change for these reasons. The triage of issue 01 found no lineage read across a call in the 8 caches that this pattern gives.

Source: issue 01 of this directory.

**Blocked by:** 01

**Category:** enhancement

**Status:** needs-triage

- [ ] A decision: add the report, or keep `CREATE TABLE` undetected.
