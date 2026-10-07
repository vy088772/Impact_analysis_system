# 10 — `MethodInfo.sql_queries` keeps the source order

**What to build:** `_extract_sql_in_text` in `code_analyzer/csharp_parser.py`
removes duplicates with `list(set(sql_queries))`. The order of a Python set
of strings changes per process, because the string hash seed changes. Thus
two scans of the same source give a different `MethodInfo.sql_queries` order.

Remove the duplicates and keep the order of the first match in the source
(for example `list(dict.fromkeys(sql_queries))`). The set of queries does not
change.

**Blocked by:** None.

**Status:** needs-triage

- [ ] Two scans of the same source give the same `sql_queries` list for each
      method, with no sort
- [ ] Each query in the list is the same as before; only the order changes
- [ ] A decision on the cache version is in the notes: the cached order is
      random, so a rescan is not necessary for correct data

**Notes:**

- Source: ticket 04 (2026-10-07). The RTTalentDB rescan differed from the old
  cache in 43 files. All 43 differences were the order of `sql_queries`. With
  each list sorted, the two scans were equal.
- Effect today: a byte compare of two scans fails. A scan compare must sort
  this list first. No known user-facing output depends on the order. Check
  this before the change.
