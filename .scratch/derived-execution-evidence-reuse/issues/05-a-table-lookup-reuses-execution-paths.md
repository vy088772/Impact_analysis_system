# 05 — A table reverse lookup reuses Execution Paths as well

**What to build:** Asking which programs touch a table stops rebuilding every
Execution Path in the SQL Execution Graph on every request. This is where the
measured eighty-eight to ninety-seven seconds goes away.

The decisive test is two questions naming two different tables in one scope. If
they derive once between them, the claim that the derivation is independent of
the question is no longer an argument — it is enforced. That is the property the
whole effort rests on, and it cannot be demonstrated by repeating one question.

The table lookup blends two sources of matches: those found by comparing table
names embedded directly in C# source, and those found by following the SQL
Execution Graph. Only the second is affected here. The blending and its
preference rule stay exactly as they are, because a faster lookup that quietly
changed which of two overlapping matches wins would be a changed answer.

**Blocked by:** 04 (extends the same retention and the same freshness rules).

**Status:** done

- [x] Two consecutive table lookups in one scope build Execution Paths once
- [x] Two lookups naming different tables in one scope derive once between them
- [x] The answer is identical with reuse active and with reuse defeated — for a
      table with matches, a table with none, and a `write_only` query
- [x] `write_only` filtering behaves exactly as it does today
- [x] The preference rule that blends embedded-SQL matches with graph-derived
      matches is unchanged
- [x] Path building is covered by the same validity stamp and the same explicit-
      refresh rule as the rating step, with no second, weaker set of rules
- [x] The lookup's response is unchanged in shape and content
- [x] Tests assert derivation counts rather than elapsed time, at the same seam
      as the previous ticket

**Note:** `find_by_table()`'s two expensive steps — rating (already retained by
ticket 04) and Execution-Path building (this ticket) — are now both served from
the *same* per-scope retention entry, `_RetainedRatedInvocations` in
`service/analyze_service.py`. That dataclass gained one field,
`execution_paths: Optional[List[...]] = None`, and a new function,
`_execution_paths_for_scope()`, calls `_rated_execution_invocations_for_scope()`
(ticket 04, unchanged) and then builds `execution_paths` onto that *same*
retained entry only when the field is still `None`. This introduces no second
validity stamp and no second freshness rule: Execution Paths are a pure
function of `_rated_execution_invocations_for_scope()`'s own two outputs
(`rated_invocations`, `graph`), and that call already guarantees a matching
retention entry is left behind — untouched (so a previously-built
`execution_paths` survives) on a stamp hit, or wholesale replaced with a fresh
`execution_paths=None` entry on a stamp mismatch or `refresh=True`. Because the
entry is keyed by scope alone, never by table name, two lookups naming
different tables in one scope share one entry and therefore derive once
between them — the property the whole ticket rests on holds by construction,
not by coincidence of a test fixture.

`service/graph_queries.py`'s `query_table_accesses()` was split into itself
(kept, same signature and behaviour, still used directly by
`service/flow_chain_builder.py` and by `tests/test_graph_queries.py`) plus a
new `filter_table_accesses(paths, graph, table_name, *, access)`, which does
everything `query_table_accesses()` used to do except build the paths — that
part is what `_execution_paths_for_scope()` now owns. `find_by_table()` in
`service/analyze_service.py` was rewired to call `_execution_paths_for_scope()`
once and then `filter_table_accesses()` per table, instead of rating C# facts
and building paths itself on every call. `write_only` filtering and the
embedded-SQL/graph-derived preference rule (`_prefer_table_match`,
`_table_match_rank`) are untouched — neither appears in the diff.

Added `tests/test_derived_execution_evidence_reuse_table.py` (10 tests),
sharing the `RatedInvocationsRetention` snapshot/restore fixture from ticket
04 and mirroring that ticket's counting-wrapper idiom, but with two counters
instead of one — one on `_rated_execution_invocations` (the rating step) and
one on `build_execution_paths` (the path-building step) — since this ticket's
claim is about the second, larger step specifically. The decisive test,
`test_two_different_table_names_in_one_scope_derive_once_between_them`, asks
about two different tables in one scope and asserts both counters read 1,
proving reuse does not depend on which table was asked about, not just on
asking the same one twice. Also covers: answer equivalence with reuse active
vs. manually defeated, for a table with matches, one with none, and a
`write_only` query; `write_only` still excludes a table reached only by a
READ; the embedded-SQL/graph-derived preference rule still prefers a
graph-derived write over an inline read for the same file; a changed
repository scan forces both a fresh rating and a fresh path build (2 calls
each across two lookups); an explicit `refresh=True` always rebuilds both,
every time (3 calls each across three lookups, two of them refreshed); and a
response built from a fully reused entry is field-for-field identical to one
built in a brand-new, never-cached scope.

Confirmed two of these tests actually detect regression rather than passing
vacuously: ran the full new file against the pre-ticket-05 code (`git stash`,
which does not touch the new untracked test file) and watched
`test_two_consecutive_table_lookups_in_one_scope_build_execution_paths_once`,
`test_two_different_table_names_in_one_scope_derive_once_between_them`,
`test_a_changed_repository_scan_causes_a_fresh_path_build`, and
`test_an_explicit_refresh_always_rebuilds_execution_paths` fail there (build
counts of 2 instead of 1, and 0 instead of 2/3 — the last because the old code
never calls `analyze_service.build_execution_paths` at all, it goes through
`graph_queries.query_table_accesses()` instead), then restored the change and
watched all four pass. The other six tests in the file pass on both sides, as
expected — they assert correctness, not reuse.

Ran the full suite before and after (`git stash` / restore, excluding the two
ODBC-driver collection failures already known from tickets 03/04) and diffed
the failing-test lists: identical, the same 12 pre-existing failures on both
sides, none touching this change (603 passed after vs. 599 before, the
difference being this ticket's own 4 net-new-passing tests plus this file's 6
already-passing ones counted only once each side).

Two review sub-agents ran the Standards and Spec axes in parallel against the
diff. Spec came back fully clean: all eight checklist items verified directly
against the implementation (not just the tests), confirmed
`query_table_accesses()`'s only other caller (`flow_chain_builder.py`) still
works unchanged, and confirmed `write_only`/the preference rule do not appear
in the diff at all. Standards found no hard violations; one judgement call
was fixed — the decisive different-tables test did not cite `ADR-0013` the
way ticket 04's analogous "does not depend on which question was asked" test
does, so the citation was added to its docstring for consistency. Two other
judgement calls were noted and accepted rather than changed: `_wire`/`_file`
and the counting-wrapper helper are near-duplicates of ticket 04's test file
(matching that file's own precedent of keeping scan/wire builders local
rather than shared), and `_execution_paths_for_scope()` indexes
`_rated_invocations_retention[scope]` directly rather than defensively,
relying on the documented invariant that the call just above it always
leaves a matching entry behind.
