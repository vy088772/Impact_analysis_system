# 01 — Inline SQL that runs a stored procedure reaches the reverse lookup

**What to build:** A stored procedure the application runs through inline SQL
text is findable by `/find_by_sp`. Today it is not, in two ways: a bare
procedure name yields no target at all, and a target that is already rated
`proven` is never read by anything that answers a lookup.

**Blocked by:** None.

**Status:** resolved

- [x] A command text that is one possibly-qualified identifier and nothing else yields an Embedded Procedure Target, recording `implicit_exec` where an explicit `EXEC` records `exec_keyword`.
- [x] Leading whitespace and SQL comments are skipped before that judgement, the same way the `EXEC` scan skips them.
- [x] A command text with a further *token* after the identifier yields no target — an argument, an operator, another statement. An ordinary `SELECT`/`INSERT`/`UPDATE`/`DELETE`/`MERGE` statement is unchanged.
- [x] Trailing whitespace, comments, and one statement terminator do not count as that token: `usp_Foo;` and `usp_Foo -- run it` execute `usp_Foo` and are recognised. (This widens the criterion as first written, which said "anything after the identifier" — a terminator changes nothing about what the batch runs, and rejecting it was a false negative.)
- [x] A bare name still passes the existing catalog rating: confirmed in the resolved database is `proven`, everything else keeps the rating it would get from an `EXEC` target with the same name. A lone word that is really a statement (`COMMIT`, `GO`) is left to that rating rather than a keyword denylist, which would be a second rule competing with the catalog.
- [x] `DbInvocation.executed_procedure_name` answers "which procedure does this invocation run" from `procedure_name`, else from a `proven` Embedded Procedure Target.
- [x] A target rated `likely`, `unresolved`, or `not_applicable` answers nothing.
- [x] A declared `procedure_name` always wins; the property never prefers a target over it.
- [x] `procedure_name`, `invocation_mode`, the evidence rating, and every Contract-derived field are untouched. The target stays additional evidence, as `test_external_text_wrapper_keeps_inline_exec_target_as_additional_evidence` requires.
- [x] `find_by_sp` reads the new property, so both paths reach it without a second rule.
- [x] A `find_by_sp` match row names the procedure it matched and says how it was named: `SPMatchProgram.procedure_name_source` is `declared`, `exec_keyword`, or `implicit_exec`. Without it the row for an inline-SQL call carried an empty `procedure_name` and no provenance at all.
- [x] `find_by_sp` returns the three programs that call `usp_PUR_SO_ChangeReason`.

## Implementation notes

- Extraction: `code_analyzer/csharp_analysis_gateway.py` — `_embedded_exec_target`
  gains the implicit-`EXECUTE` case via `_implicit_exec_target`; `_SQL_IDENTIFIER`
  and `_skip_sql_leading_trivia` already existed for it. `EmbeddedProcedureTarget`
  gains `target_source`.
- The question: `DbInvocation.executed_procedure_name` /
  `executed_procedure_schema`, read by `service/analyze_service.find_by_sp`.

## Comments

An earlier attempt promoted a proven target into `procedure_name` itself. Ten
existing tests failed, and one of them —
`test_external_text_wrapper_keeps_inline_exec_target_as_additional_evidence` —
names the decision that promotion would have reversed: an embedded target is
additional evidence, deliberately not the invocation's procedure. Naming the
question instead leaves that decision intact and every one of those tests green.

Measured on the `Y-Docs_TTPUR` scan, contract `sqlobject-4195c73e585b`:
510 → 541 stored procedures reachable by the reverse lookup, none lost. 6 come
from bare names, 25 from `EXEC` targets that were already rated `proven` and had
no reader. `find_programs_by_sp` returns all three callers of
`usp_PUR_SO_ChangeReason`.

Two limits are inherited from the existing `_SQL_IDENTIFIER`, shared with the
`EXEC` extractor and unchanged here: a bracketed identifier accepts any content
(`[usp; drop table x]` reads as one identifier, and the catalog rating is what
rejects it), and a double-quoted identifier (`"dbo"."usp_Foo"` under
`QUOTED_IDENTIFIER ON`) is not recognised at all. Both predate this change and
apply to the `EXEC` form the same way.
