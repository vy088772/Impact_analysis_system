# 02 — Delete the unreachable dependency producer

**What to build:** Remove the `SQLAnalyzer` method that queries `sys.sql_expression_dependencies` and builds the legacy `depends_on`/`depended_by` dict. It has zero production callers — the code that assembles a SQL cache payload (`dump_all_sql_objects()`) never calls it. Its only reference outside its own definition is a test stub standing in for a call that method never makes.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] The producer method is deleted from `SQLAnalyzer`.
- [x] The now-pointless test stub that assigned a lambda replacement for this method is removed from the test that checks later `SQLAnalyzer` helpers stay on the class after progress reporting was added; that test's own assertions are otherwise unchanged.
- [x] A repo-wide search confirms no remaining reference to the deleted method outside of this change's own diff and the ADR from ticket 01.
- [x] The affected test file passes.

**Note:** Deleted `SQLAnalyzer.get_all_dependencies()` (the `sys.sql_expression_dependencies`
query and the `depends_on`/`depended_by` dict it built) from
`code_analyzer/sql_analyzer.py`. Removed the matching stub line
(`analyzer.get_all_dependencies = lambda schema: {}`) from
`test_dump_all_sql_objects_keeps_sp_helpers_on_sql_analyzer` in
`tests/test_sql_execution_graph.py`; that test's other stubs and assertions are
unchanged. `grep -rn get_all_dependencies` across the repo now matches only
`docs/adr/0031-retire-the-legacy-dependency-dictionary-pipeline.md` and ticket 01's
own file — no other reference remains. `tests/test_sql_execution_graph.py` passes
(11 passed). Full suite run for regressions: 1041 passed, 16 failed; all 16
failures are pre-existing and unrelated (confirmed by re-running
`tests/test_program_refresh.py` after `git stash` — same 3 failures with this
change reverted), none reference `get_all_dependencies`. Two-axis code review
(Standards + Spec, via parallel sub-agents) found zero issues on both axes.
