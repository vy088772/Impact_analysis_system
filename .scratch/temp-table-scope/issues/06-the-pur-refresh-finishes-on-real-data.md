# 06: The PUR refresh finishes on real data

**What to build:** The operator refreshes PUR on the refresh machine with the
new code. The refresh ends, and the lineage answers make sense. After this
ticket, the canonical-object-identity operator action can continue.

See "Further Notes" in the spec.

**Repositories:** this repository and `llamaindex-spec-rag`, deployed together.

**Blocked by:** 04, 05.

**Status:** ready-for-human

- [ ] Both repositories are deployed to the refresh machine.
- [ ] `refresh_sql_cli PUR` reaches the cache write stage and prints its result.
- [ ] The `lineage` stage on PUR ends in 30 seconds or less.
- [ ] The new PUR cache holds the new graph version.
- [ ] From the new PUR cache, the two or three temp table names that the most procedures share are picked. For each, a `/find_by_table` answer lists no unrelated procedure.
- [ ] A "parent creates, child fills" pattern in PUR keeps its base tables in the `/find_by_table` answer.
