# 07 — Wrapper command text resolves from a same-method variable

**What to build:** An analyst asking which stored procedures a program touches gets an answer for
a system written in the ordinary style, where the procedure name is assigned to
a local variable or a field a few lines above the call.

Wrapper command text resolves today only from a string literal written at the
call site. In one measured repository that is 1 call out of 262. The tracer that
walks an identifier back to the declarations and assignments preceding it inside
the same method already exists and is already tested; it is wired to the direct
ADO.NET path and not to the wrapper path.

A command text that arrives as a method parameter stays unresolved, on purpose
(ADR-0020).

**Blocked by:** 06.

**Status:** done

- [x] A wrapper call whose command text is a local variable assigned a literal earlier in the same method resolves its Executed Procedure Name.
- [x] A wrapper call whose command text is a field assigned a literal earlier in the same method resolves its Executed Procedure Name.
- [x] A wrapper call whose command text is a literal at the call site resolves exactly as it does today.
- [x] A wrapper call whose command text arrives as a method parameter stays unresolved and carries its own reason code.
- [x] A variable with two conflicting literal assignments before the call stays unresolved rather than picking one.
- [x] The measured Core repository resolves at least 250 of its 262 wrapper calls to a procedure name.
- [x] The WebForms baseline is re-run: stored procedure and table relation counts do not fall, and any rise is attributable to this rule.

## Note

### Where the fix actually lives

`ReadWrapperCommandTextCandidates` (`WrapperAnalyzer`) already walked an identifier back to its
same-method declarations and assignments — but only the *source-available* wrapper path called it
(the one where the wrapper method's own body is visible in the scanned repository). Every measured
Core repository's data access instead goes through the *external* wrapper path
(`WrapperAnalyzer.CreateUnavailableCandidate` / `CreateUnavailableInvocation`, `tools/StaticAnalyzerHost/CSharpAnalyzer.cs`)
— the wrapper method is declared in an assembly this analysis cannot see (`SQLDbContext` in
IQCS's case, ticket 06). That path read command text only from
`ResolveExternalCommandTextArgument`, a raw call-site argument, with no tracing at all: anything
but a literal at the call site read as `"dynamic"`.

The whole fix is one new function, `ResolveExternalCommandText`, that:

- Reuses the existing tracer (`ReadWrapperCommandTextCandidates`'s low-level identifier-walking
  overload) instead of reading the call-site argument directly.
- Recognizes a command text that is the caller's own parameter *before* tracing, and reports
  `command_text_method_parameter` rather than a value the tracer could ever resolve to `"dynamic"`
  the same way a genuinely computed expression does.
- Recognizes when tracing finds more than one surviving literal (e.g. one assignment on each side
  of an `if`/`else` that both reach the call unconditionally) and reports
  `command_text_conflicting_assignments` instead of silently keeping the first or the last.

`DirectSqlInvocation` gained one new field, `CommandTextUnresolvedReason`
(`command_text_unresolved_reason` over JSON), carried through
`CreateUnavailableInvocation`. On the gateway side (`code_analyzer/csharp_analysis_gateway.py`),
the two `"dynamic_command_text"` sites inside `_resolve_wrapper_invocation`'s external-wrapper
branch now read `_command_text_unresolved_reason(raw)`, which prefers the host's own reason when
one is given. Nothing else needed to change: `command_text_kind` / `command_text` already flowed
generically from the raw C# facts into `procedure_name` resolution for every wrapper kind, so a
traced literal reaches the Executed Procedure Name exactly the way a call-site literal always did.

### The two limits, both deliberate

**A command text does not cross a method boundary.** A parameter carries no in-method assignment
to trace by construction (ADR-0020); tracing further would be interprocedural constant
propagation, out of scope for this ticket and the rest of the epic.

**Two conflicting assignments are a real ambiguity, not a branch split.** The direct-ADO.NET path's
own tracer already treats an `if`/`else` pair of assignments as two legitimately different
*branch-scoped* answers when the call itself sits inside one of those branches. Here, both survive
shadow-removal only when the call is reachable from either branch without distinguishing them —
genuine ambiguity, not two provably-distinct call sites. `CreateUnavailableCandidate` returns one
`DirectSqlInvocation` per call, so this collapses to one unresolved row rather than guessing.

### Measured

**IQCS, the repository ADR-0020 was written against** (267 files, real clone, real host,
`data/repos/System_Dept_1/IQCS`): every one of its 262 calls keyed on `SQLDbContext`
(ticket 06) now resolves a literal command text — **262 of 262**, ahead of the 250 the ticket asked
for. ADR-0020 had predicted roughly 254, with 8 held back by a `sqlCmd`-shaped indirection; those
resolved too once the tracer's existing `ConditionalExpressionSyntax`/shadow-removal handling ran
against the real file. Broken down by wrapper method:

```
usp_ExecCmdGetDataTableAsync   196
usp_ExecCmdGetDataSetAsync      62
usp_ExecCmdGetJsonObjectAsync    3
usp_ExecCmdGetCountAsync         1
                              ----
                               262  (all literal, 0 dynamic)
```

This is a host-level measurement (same methodology ticket 06's own note used): it counts
`command_text_kind == "literal"` directly from `StaticAnalyzerHost`, not through a registered
`SQLDbContext` Contract reconciled by the gateway — no such Contract exists yet, and creating one
is Contract Onboarding's job (ticket 06's note), not this ticket's.

**Y-DOCs WebForms baseline** (`.scratch/aspnet-mvc-core-analysis/baseline-ydocs.json`, captured
before ticket 07, all five scan roots: TTPUR, ATV, Notification, Response, TaskSchedule), re-run
against the same on-disk checkout with this change in place:

| | before | after |
| --- | --- | --- |
| `sp_relations` | 637 | 637 |
| `table_relations` | 392 | 392 |

Unchanged, not merely non-falling — this rule's own precondition (a call must first be recognised
as an *unavailable external wrapper candidate* with no local `WrapperDefinition`) already held for
every WebForms call this baseline covers, so no new call gained or lost a literal here. The rerun
used `service.scan_store.get_or_scan(root, refresh=True)` directly (forces a genuine rescan through
the updated host) reached through `service.repo_manager.peek_scan_roots` (resolves the same five
paths with no `git pull`), rather than the `/refresh` endpoint's full `refresh_source`, to avoid a
network/git action against a checkout that ADR/spec already records as carrying uncommitted local
`Web.config` edits out of this ticket's scope. The rerun's own `wrapper_totals` figures are not
comparable to the baseline's for that reason (the baseline's were produced against the real
Contract registry; this rerun used an empty one for speed) — only `sp_relations` /
`table_relations`, this ticket's actual acceptance criterion, are.

### Tests

`tests/test_wrapper_command_text_same_method_variable.py`, seven tests against a minimal synthetic
external-wrapper fixture (no real project file needed — `CreateUnavailableCandidate` works
syntax-only): local variable, field, call-site literal unchanged, method parameter, conflicting
assignments, and two gateway-seam tests confirming a traced literal reaches
`executed_procedure_name` and that `command_text_method_parameter` survives into the rated
`DbInvocation.reason`.

One pre-existing test needed updating, not reverting:
`test_static_analyzer_host_preserves_external_inline_non_prefix_and_dynamic_facts` had a
`DynamicData(string commandText)` fixture whose command text arrives as a parameter — exactly this
ticket's case. Its assertion moved from the generic `"dynamic_command_text"` to
`"command_text_method_parameter"`, which is the whole point of naming a narrower reason.

Three other pre-existing failures in `tests/test_csharp_analysis_gateway.py`
(`test_resolved_invocation_retains_wrapper_reconciliation_provenance`,
`test_external_wrapper_contract_requires_explicit_selection_even_for_unique_receiver_type`,
`test_static_analyzer_host_applies_external_sqlobject_wrapper_contract`) were confirmed
pre-existing by stashing this change and re-running: identical failures, identical assertions, on
the commit this ticket started from. Unrelated to command text; left untouched.

`pytest`: full suite green apart from those same three pre-existing failures.
