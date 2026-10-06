# 01 — A primary constructor parameter resolves the wrapper receiver type

**What to build:** `ResolveExternalReceiverType` in
`tools/StaticAnalyzerHost/CSharpAnalyzer.cs` also reads the parameter list of
the class that contains the caller. That list is a C# 12 primary constructor,
for example `class JobTypeService(RTTalentDBContext _context)`. A primary
constructor parameter is the same kind of declaration as a field or a method
parameter, which the resolver already reads. So the call
`_context.usp_ExecCmdGetDataTableAsync("dbo.usp_MS_GetJobType")` gets the
receiver type `RTTalentDBContext`. `ResolveWrapperReceiverType` then re-keys
it to the declaring type `SQLDbContext`, as it does today for a method
parameter.

The rule from commit `67dbb22` (ticket 06 of the receiver work) stays: the
host walks only from a receiver type that the syntax resolved. This ticket
adds one more syntax source. It does not fill a receiver type from the bound
symbol alone. So the `wrapper_review_exclusions.json` entries keyed on an empty
receiver type keep their meaning.

**Blocked by:** None — can start immediately.

**Status:** done (pending code review)

- [x] A wrapper call whose receiver is a primary constructor parameter of the
      containing class reports `wrapper_receiver_type` equal to the declaring
      type of the invoked method, with provenance `declaring_type`
- [x] A local variable, a method parameter, a field, or a property with the
      same name as a primary constructor parameter still wins, in the order
      the resolver reads them today (C# name lookup gives the inner scope
      first)
- [x] A call whose receiver the syntax does not resolve (`Path.Combine`,
      `ColorTranslator.FromHtml`, `dt.Columns.Add`) reports no receiver type,
      the same as today
- [x] A record type with a primary constructor counts the same as a class
- [x] A host test covers a primary constructor receiver that inherits the
      wrapper method from an external base type, the RTTalentDB shape
- [x] After a local rescan of RTTalentDB, the probe below reports at least
      215 `proven` of the 228 `SQLDbContext.` calls (today: 2)
- [x] After the rescan, `/find_by_sp` for `usp_MS_GetJobType` on RTTalentDB
      returns `JobTypeService.GetJobTypeList` (today: no match)
- [x] The other systems that use `SQLDbContext` (IQCS, EnterpriseApi,
      EnterpriseApp, ETR) keep their call count; a change in their proven
      count is listed in the notes with its cause

**Feedback loop:**

```
cd Impact_analysis_system
.venv/bin/python .scratch/rttalentdb-program-to-sql-chain/probes/probe_receiver.py           # rates the cached scan
.venv/bin/python .scratch/rttalentdb-program-to-sql-chain/probes/probe_receiver.py --patch   # the expected result
```

Baseline 2026-10-06 (scan `f681f601165fe4e8`, contract
`sqldbcontext-50a129cdf273`):

| | proven | likely | unresolved |
|---|---|---|---|
| Today | 2 | 0 | 226 (`receiver_mismatch`) |
| `--patch` (receiver filled in memory) | 215 | 3 | 10 |

The 10 that stay unresolved are expected: 9 are `command_text_method_parameter`
(ADR-0020), and 1 is `spAddRecordError`, rated against the RTTalentDB catalog
while it lives in SysErrorRecord.

**Notes:**

- Root cause: `ResolveExternalReceiverType` reads local variables (a `var`
  local only with `new T()`), method parameters, fields and properties. It
  never reads `ClassDeclarationSyntax.ParameterList`. Then
  `ResolveWrapperReceiverType` returns `ResolvedReceiverType.None` before it
  reads `boundSymbol.DeclaringTypeName`.
- Discriminator across all 228 calls: the 2 that resolve today are in
  `Middlewares/AuthMiddleware.cs`, where `_context` is a method parameter of
  `Invoke`. The 218 calls in primary constructor classes report `None`.
- Commit `67dbb22` measured RTTalentDB at 2 re-keyed calls against IQCS at
  262. Nobody followed up on that gap.
- Out of scope: `var _context = …GetRequiredService<RTTalentDBContext>()` in
  `Attributes/*AuthChkAttribute.cs` (3 calls). Those calls also miss a
  connection source, so they rate `likely` even with a receiver type.
- The scan cache must be rebuilt locally after the host change. The operator
  replaces only the SQL caches.
- `CSharpAnalyzer.cs` line endings: check `git diff --stat` before commit, so a
  whole-file CRLF/LF change does not slip in.
- Related: ticket 02 (method declarations), and ticket 03 (grilling on the
  call graph across files).

**Implementation notes (2026-10-06):**

- `ResolveExternalReceiverType` now reads the primary constructor parameter list as its
  last source, after local variable, method parameter, field and property. A member with the
  same name wins, as in C# name lookup. The containing type match widened from
  `ClassDeclarationSyntax` to class or record (`TypeDeclarationSyntax`).
- Tests in `tests/test_wrapper_receiver_declaring_type.py`: the real RTTalentDB
  `JobTypeService` (external base `SQLDbContext`), and a synthetic source for class, record,
  method-parameter precedence, and `Path.Combine` / undeclared receivers with no type.
- Local rescan of RTTalentDB: 215 `proven` of 228 `SQLDbContext.` calls (was 2). The rest:
  9 `command_text_method_parameter`, 1 `not_in_resolved_catalog`, 3 `receiver_mismatch`
  (the out-of-scope `var _context = ...GetRequiredService` calls). Receiver type is set on
  225 of 228 calls (was 2).
- `usp_MS_GetJobType`: the rated calls now include `JobTypeService.GetJobTypeList` and
  `JobDutyService.GetJobDutyViewModel`, both `proven`. Checked on the rated invocations that
  `find_by_sp` reads, not through the endpoint, which needs the operator SQL graph cache.
- Other `SQLDbContext` systems, scan-level before/after (receiver-keyed calls equal total):
  IQCS 262/262, ETR 1/1, EnterpriseApi 118/118, EnterpriseApp 80/80. No change.
- Scan caches of these five systems were rebuilt locally by the measurement.
