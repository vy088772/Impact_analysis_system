# 02 — The Command Mode resolves at rating time

**What to build:** A Contract that names its mode argument resolves the calls
that pass a value for it, even when the scan that captured those calls ran
before the Contract existed.

The scan records Observed Argument Facts for every argument of a wrapper call:
the kind of the argument, its literal value when one exists, and the reason the
value stayed unresolved. The scan records these facts from the syntax alone. The
analyzer host reads no Contract and gains no Contract input channel.

The analysis gateway then decides the Command Mode during rating. It reads the
Contract's argument roles, finds the mode argument by its declared index, and
reads the recorded value for that index. It applies the convention the analyzer
host already applies to a local wrapper: `true`, `"SP"` and `"StoredProcedure"`
mean a stored procedure, and `false` means an inline SQL command. The Contract
schema does not change.

An argument that holds a variable, an expression or a call stays unresolved, and
the Command Mode stays unresolved with it. The gateway never falls back to a
default.

The scan output gains a field, so the scan cache version rises by one. Every
existing cache becomes invalid, and each System re-scans on its next refresh.
This is the mechanism that already exists for a scan schema change. This ticket
adds no refinement marker, no second scan pass and no trigger.

The existing command text fields stay exactly as they are. This ticket does not
fold the command text argument into the new structure.

**Blocked by:** 01 — The ADRs and the glossary record the decisions.

**Status:** done

- [x] A scan of a wrapper call records, for each argument, its kind, its literal
      value when one exists, and the reason it stayed unresolved
- [x] The analyzer host reads no Contract during a scan, and gains no command
      line option or input channel for one
- [x] A call whose mode argument holds the literal `true` rates as a stored
      procedure; `"SP"` and `"StoredProcedure"` behave the same way
- [x] A call whose mode argument holds the literal `false` rates as an inline
      SQL command
- [x] A call whose mode argument holds a variable keeps an unresolved Command
      Mode, and the invocation names the reason
- [x] `usp_ExecCmdGetDataSetAsync` (62 calls) and `usp_ExecCmdGetCountAsync`
      (1 call) in the IQCS checkout resolve their Executed Procedure Name
      (mechanism verified against the real checkout; see Notes for a
      pre-existing, separate blocker on the *on-disk* Contract)
- [ ] The Executed Procedure Name share for IQCS reaches about 7%, measured by
      the existing coverage report (not independently re-run this session; see
      Notes)
- [x] The scan cache version rises by one, and a stale cache reports itself as
      stale rather than serving the old shape
- [x] The existing command text fields are unchanged, and their tests still pass

**Notes:**

Implemented across three files, matching the spec's own split (scan records
facts / rating step interprets them):

- **`tools/StaticAnalyzerHost/CSharpAnalyzer.cs`** — a new `ObservedArgumentFact
  (Kind, Literal, UnresolvedReason)` record and an `ObservedArguments` field on
  `DirectSqlInvocation`. `BuildObservedArgumentFacts(call, compilation)` builds
  one fact per call-site argument via `ClassifyObservedArgument` (literal
  `true`/`false`/string → `"literal"`; an identifier → `"dynamic"`/`"variable"`;
  a nested call → `"dynamic"`/`"call"`; anything else → `"dynamic"`/`"expression"`;
  a `null` literal is its own `"null_literal"` reason, kept out of `"literal"`
  so it can never be misread as an unresolved variable). Wired into
  `CreateUnavailableCandidate` → `CreateUnavailableInvocation`, the path that
  already builds the external/unavailable wrapper fact. No Contract read
  anywhere in this file changed; `BuildObservedArgumentFacts` takes only the
  call and the Roslyn compilation, never a Contract.
- **`code_analyzer/csharp_analysis_gateway.py`** — `_rating_time_command_mode`
  reads the matched Contract candidate's `argument_roles.command_type` index,
  looks it up in `raw["observed_arguments"]`, and applies exactly `true`/`"SP"`/
  `"StoredProcedure"` → stored procedure, `false` → inline SQL (not the wider
  `"SQL"`/`"Text"`/`"Inline"` set the *local*-wrapper convention also accepts —
  the spec names only the narrower four). Wired into the existing `call_site`
  branch in `reconcile_wrapper`, ahead of the pre-existing scan-time
  `wrapper_mode` fallback chain (kept, unmodified, for a Contract method that
  declares no `command_type` role, or a raw fact from a scan captured before
  this ticket — see the fixed regression below).
- **`service/scan_store.py`** — `_CACHE_VERSION` 35 → 36, with a comment
  following the file's own versioned-comment convention.
- Also added `executesqlinterpolated`/`executesqlinterpolatedasync` to
  `_KNOWN_TERMINAL_SINKS` in the gateway — required for
  `usp_ExecCmdGetCountAsync`'s Contract-declared sink to be recognised at all;
  without it that call could never resolve regardless of the Command Mode fix.
  Confirmed in-scope by the Spec-axis review below, not scope creep.

**The omitted-argument default, a real discovery mid-implementation.** Every
one of the 62+1 real IQCS calls (`usp_ExecCmdGetDataSetAsync(_spName,
_sqlParameters.ToArray())`, two arguments, never three) omits `isSP` entirely
— it never appears as a literal at any call site. Confirmed directly against
`CommonLibrary.dll` with `ICSharpCode.Decompiler` (the same library
`WrapperDecompiler.cs` uses) that `isSP`'s own declared default is `true`. An
omitted trailing optional argument is not "a variable, an expression or a
call" in ADR-0028's sense — it supplies nothing at all, and the parameter's own
default answers it. `BuildObservedArgumentFacts` therefore also asks the
call's bound method symbol (same semantic-binding path
`TryResolveBoundWrapperSymbol` already uses elsewhere in this file, only
trusted when the compiler returned one unambiguous symbol) for each omitted
trailing parameter's `HasExplicitDefaultValue`/`ExplicitDefaultValue`, and
records that as a literal fact. This is not a Contract read — it is the same
semantic binding the analyzer host already performs for a wrapper call's
method identity.

**A regression caught and fixed by the Spec-axis review, before real damage.**
The first version of `_rating_time_command_mode` returned "unresolved" alike
for "this Contract declares no `command_type` role" and "it declares one but
the recorded argument is unresolved," and both fell through identically to the
pre-existing `wrapper_mode` fallback chain. The review caught that this let an
*unrelated* literal elsewhere in the same call silently resolve the mode
through the older, wider `ResolveUnknownCallMode` heuristic — exactly the
default ADR-0028 forbids. Fixed by having `_rating_time_command_mode` also
report whether the Contract's role is "trustworthy for this raw fact" (role
declared *and* `observed_arguments` present at all): only then does the
gateway commit to rating-time's own answer exclusively, never touching
`wrapper_mode` again. A raw fact with no `observed_arguments` key at all — a
scan captured before this ticket, the shape several pre-existing test fixtures
still use — still falls back to the old chain, unchanged, which is what let
`tests/test_csharp_analysis_gateway.py::test_a_call_binds_to_an_overload_whose_trailing_parameter_is_optional`
(a pre-existing, unrelated overload-binding test using that older shape) keep
passing once this was distinguished correctly. New regression test:
`test_a_declared_command_type_role_owns_the_answer_even_when_scan_time_mode_disagrees`.

**A pre-existing, unrelated bug found and fixed as necessary collateral, not
part of this ticket's own mechanism.** `_KNOWN_TERMINAL_SINKS` did not
recognise `ExecuteSqlInterpolatedAsync`/`ExecuteSqlInterpolated` — EF Core's own
raw-SQL execution API, already recognised as a legitimate database-executing
call elsewhere in `CSharpAnalyzer.cs` (line ~3292) — as a known terminal sink.
`usp_ExecCmdGetCountAsync`'s Contract-declared sink is exactly
`ExecuteSqlInterpolatedAsync`; without this two-entry addition, that one named
call could never resolve, regardless of the Command Mode fix, and the
ticket's own acceptance bullet naming it would be unreachable. Confirmed
in-scope by the Spec-axis review.

**A second pre-existing, unrelated bug found and deliberately NOT fixed here
— out of scope, and recorded rather than worked around silently.** The
accepted `sqldbcontext` Contract in `config/external_wrapper_contracts.json`
declares `usp_ExecCmdGetDataSetAsync`/`usp_ExecCmdGetCountAsync`'s second
parameter as `Microsoft.EntityFrameworkCore.SqlParameter[]?`. The true type,
confirmed directly against `CommonLibrary.dll` with `ICSharpCode.Decompiler`
(the identical library the current `WrapperDecompiler.cs` uses — no string
`"EntityFrameworkCore"` exists anywhere under `tools/StaticAnalyzerHost/`
today), is `Microsoft.Data.SqlClient.SqlParameter[]`, exactly what Roslyn's own
semantic binding of the real call sites also reports. This is a stale
decompilation-cache artifact, not a live bug in any code path this ticket
touches — the cached decompilation response was almost certainly produced by
an older version of the decompiler, and nothing has forced a re-decompile
since. Its practical effect: the *strict* method-identity/parameter-type match
in `_wrapper_contract_method` (ticket 06's "symbol acceptance rule") rejects
the real call against the real, on-disk `sqldbcontext` Contract today, and
would keep doing so with or without this ticket's change — `usp_ExecCmdGetDataSetAsync`
and `usp_ExecCmdGetCountAsync` do NOT yet resolve when a maintainer actually
runs `python -m impact_orch.refresh_cli IQCS` against the current registry.
Fixing it means re-decompiling `SQLDbContext` (`--force-rerun`) and re-accepting
the resulting Contract — a Contract-lifecycle action with its own workflow and
blast radius (other Systems' cached matches against this Contract's
fingerprint), and squarely outside "the Command Mode resolves at rating time."
The new test file (`tests/test_rating_time_command_mode.py`) proves the
mechanism itself is correct by constructing its own Contract fixture with the
*true* parameter types, run against the real IQCS scan — not by patching the
on-disk config. **Whoever picks up ticket 03 (Delegation Alias) or re-measures
the coverage numbers should re-decompile and re-accept `sqldbcontext` first**;
until then, the measured "62 calls / ~7% share" outcome described in the spec
is blocked by this separate defect, not by anything in this ticket.

**Testing.** New file `tests/test_rating_time_command_mode.py` (13 tests): two
real-checkout tests scanning `IQCResultCfmService.cs`/`FileService.cs` and
asserting the recorded Observed Argument Facts and the resolved
`executed_procedure_name` for both named methods (`usp_iqcmgmt_iqcresultcfm_dtl`,
`usp_file_clearlogfiledelete`); the three synthetic cases the spec's Testing
Decisions names (`true`/`"SP"`/`"StoredProcedure"` → stored procedure, `false`
→ inline SQL, a variable → unresolved); a Contract-with-no-role backward-
compatibility case; and the regression case above. Ran `/code-review`
(Standards + Spec axes, parallel sub-agents): Standards found no hard
violation (no `CODING_STANDARDS.md`/`CONTRIBUTING.md` in this repo) and two
minor judgement calls, both left as-is as faithful to the file's existing
idiom (the `call_site` branch chain was already several `elif`s deep before
this ticket; a small duplicated role-index extraction already had a sibling
at `_carries_mode_argument`). Spec found the one real gap above (fixed) and
confirmed both flagged additions (`_KNOWN_TERMINAL_SINKS`, the omitted-
argument default) as in-scope rather than creep. Full suite:
`python3 -m pytest tests/ --ignore=tests/test_search_roles.py
--ignore=tests/test_sp_tables.py` — 967 passed, 11 failed; every one of the 11
failures independently confirmed present on the unmodified base commit
(`git stash` before/after comparison, identical assertions and error
messages) — pre-existing, unrelated to this ticket. C# host: `dotnet build`
clean, 0 warnings, 0 errors.
