# 01 — Write ADR-0031 retiring the legacy dependency-dictionary pipeline

**What to build:** An ADR recording the decision to retire the pre-graph dependency-dictionary pipeline (the `sys.sql_expression_dependencies`-based producer, the `dependency_fetcher` compatibility adapter, and the cache-write scrubber). The ADR should read as a decision record, not a changelog of the code diff: why each piece was already dead, why removing the scrubber is a real trade-off (it was a defense-in-depth guard, not a pure no-op), and what a future reader should conclude if they find one of these names in git history.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] ADR is numbered 0031 and follows this repo's existing ADR format (see ADR-0011 for the closest-shaped precedent: removing an already-unreachable path).
- [x] ADR references ADR-0001 (the SQL Execution Graph) as the decision this one completes.
- [x] ADR states plainly that the producer method had zero production callers because the code that assembles a SQL cache payload never called it — not because a caller was removed.
- [x] ADR corrects, rather than repeats, the claim that this retirement "drops one live schema query per refresh" — that query was already unreachable before this decision.
- [x] ADR states that the compatibility adapter was already graph-backed (it read the SQL Execution Graph, not the legacy dict) and explains that its removal is safe because nothing in the codebase needs the legacy `depends_on`/`depended_by` shape it produced.
- [x] ADR explains the scrubber's real role as a defense-in-depth guard against a future/alternate payload producer reintroducing the legacy field names — not as dead code being swept up incidentally.

**Note:** Written as `docs/adr/0031-retire-the-legacy-dependency-dictionary-pipeline.md`,
in ADR-0011's shape (Status/Date, Context, Decision, Consequences). Verified all
three names and claims against the actual source before writing: the producer is
`SQLAnalyzer.get_all_dependencies()` (queries `sys.sql_expression_dependencies`,
never called by `dump_all_sql_objects()`); the adapter is
`service/dependency_fetcher.py`'s `fetch_dependencies()` (its own docstring already
says it never turns legacy indexes into formal lineage); the scrubber is
`_without_legacy_dependency_fields()` in `service/sql_cache_store.py`, called inside
`get_or_dump(..., refresh=True)` right after `dump_all_sql_objects()` builds the
payload. Also read the `_SQL_CACHE_VERSION` history comment (v8/v9 already record
that legacy fields are gone from persisted caches) and `CONTEXT.md`'s SQL Execution
Graph glossary entry (already lists `dependencies`/`depends_on`/`depended_by` under
_Avoid_), both consistent with the ADR's claims — no correction needed there.

**Numbering conflict found, not resolved here:** `.scratch/remove-fk-cascade-tables/issues/03-record-adr-0031.md`
independently plans its own ADR-0031, for an unrelated FK-cascade-table decision.
Neither ADR existed before this session (highest number on disk was 0030), and that
other task has not started (no code changes, cascade resolver still present). This
ADR now occupies 0031. Whoever picks up `remove-fk-cascade-tables/issues/03` next
must renumber its ADR to 0032 (or the next free number at that time) before writing it.

Issues 02–04 in this task (delete the producer, the compatibility adapter, the
cache-write scrubber) are separate and not started.
