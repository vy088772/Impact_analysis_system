# 02 — Every method declaration shape reaches the scan

**What to build:** The C# scan records a method whose declaration has any of
these shapes. Today the scan drops each of them:

- a tuple return type: `Task<(bool Success, string Message)> InvalidateJobType(…)`
- a nullable return type: `Task<JobDuty?> GetJobDutyById(…)`, `string? NTAccount(…)`
- a generic method: `Task<List<T>> ExecuteAndMapList<T>(…) where T : new()`
- a generic return type with `, ` inside: `Task<Dictionary<string, DataTable>> …`
- a space before the type argument list: `Task <IActionResult> ImportData()`

A dropped method has no `calls` and no node in the method adjacency. So every
chain that passes through it stops there. In RTTalentDB, most add, update and
disable services return a tuple, so the chains that write data are the ones
that are lost.

**Blocked by:** None — can start immediately.

**Status:** done (2026-10-06)

- [x] **Decide first, then build.** Present the two options below to the user,
      with a recommendation, and record the answer in the notes:
      - A: widen `METHOD_PATTERN` in `code_analyzer/csharp_parser.py:280`
        (the HTTP action scan near line 1791 reuses the same pattern)
      - B: take the method list from the Roslyn host, which already parses
        each file with a semantic model
- [x] Each of the five shapes above gets a parser test with its real
      RTTalentDB declaration
- [x] A statement that looks like a declaration (`return Foo(…)`,
      `await Bar(…)`) is still not a method; the
      `_METHOD_RETURN_TYPE_DENYLIST` cases keep passing
- [x] After a local rescan of RTTalentDB, the probe below reports 0 missing
      `tuple-return` methods (today: 46 of 46 missing) and fewer than 79
      missing in total; each method still missing is listed in the notes with
      its reason
- [x] `JobTypeService.InvalidateJobType` appears in the scan, and its `calls`
      hold `usp_ExecCmdGetFisrtValueAsync`
- [x] The parser serves every C# system. Capture the method count of each
      cached system before the change, compare it after, and list each
      change in the notes. A count that rises is not proof by itself
      (ADR-0020 consequences)

**Feedback loop:**

```
cd Impact_analysis_system
.venv/bin/python .scratch/rttalentdb-program-to-sql-chain/probes/method_coverage.py data/scan_cache/f681f601165fe4e8.pkl -v
```

Baseline 2026-10-06:

```
33 ('other-return', 'MISSING')
552 ('other-return', 'in scan')
46 ('tuple-return', 'MISSING')
missing total 79
```

**Notes:**

- Root cause: the return type group of `METHOD_PATTERN` is `[\w\<\>\[\]]+`.
  It does not accept `?`, `(`, `)`, `,` or a space. The method name must be
  followed by `\(`, so `Name<T>(` does not match.
- Discriminator: tuple return types are 46 of 46 missing, with no exception.
  The other 33 missing all have `?`, `<T>`, `, ` or `Task <` in the
  declaration.
- This ticket alone does not connect the RTTalentDB chains. The forward chain
  also stops at the controller: `service/flow_chain_builder.py:174` builds
  the adjacency only from the files the program owns (ADR-0019), and
  `_method_adjacency` compares bare names while the scan records
  `'_service.InvalidateJobType'`. That third break is ticket 03 (grilling,
  blocked by this ticket), because it touches the ADR-0019 scope decision.
  Its baseline:

  ```
  cd llamaindex-spec-rag
  python3 ../Impact_analysis_system/.scratch/rttalentdb-program-to-sql-chain/probes/truth.py \
      ../Impact_analysis_system/data/repos/System_Dept_1/RTTalentDB/RTTalentDB \
      ../Impact_analysis_system/.scratch/rttalentdb-program-to-sql-chain/probes/truth.json
  PYTHONPATH=. .venv/bin/python ../Impact_analysis_system/.scratch/rttalentdb-program-to-sql-chain/probes/compare_flow.py flow_after.json
  ```

  2026-10-06: 0 of 227 actions reach their stored procedures through
  `rag_client.flow_chain`; 244 of 261 chains stop at the action itself.
- The scan cache must be rebuilt locally after the change.
- Decision (2026-10-06, user): option A. `METHOD_PATTERN` is widened. The
  Roslyn host is not used for the method list. The HTTP action scan reuses
  the same pattern, so it gets the same shapes.
- Change: return type (group 7) accepts a tuple `(bool A, string B)`, a
  generic with `, ` and a space before `<`, `?`, and `[]`. The method name
  accepts `Name<T>(`. Group numbers 7 and 8 stay the same. Tests are in
  `tests/test_csharp_parser_method_declaration_shapes.py`. Cache version is
  now 45 (`service/scan_store.py`).
- RTTalentDB probe after local rescan: 585 in scan, 46 `tuple-return` in
  scan, 0 missing in total (before: 79 missing). No method is left missing,
  so there is no reason list.
- `JobTypeService.InvalidateJobType` is in the scan. Its `calls` hold
  `_context.usp_ExecCmdGetFisrtValueAsync`. The receiver prefix is the
  existing scan format. The bare-name match is ticket 03.
- Method count per cached system (re-parse of each cached file, old regex
  vs new regex; 0 file gone, 0 parse failure counted). Two cache ids hold
  the same RTTalentDB source (`cc198a82fcd36afa`, `f681f601165fe4e8`).

  | cache id | before | after | change |
  |---|---|---|---|
  | 0b77df8ccb218630 | 67 | 67 | 0 |
  | 3411f5121129666d | 38 | 38 | 0 |
  | 34cf52ca745151b7 | 1325 | 1326 | +1 |
  | 364395b8fe8c7ca4 | 289 | 340 | +51 |
  | 8c321687c29bb37c | 66 | 66 | 0 |
  | 911a9596f255acef | 3125 | 3182 | +57 |
  | 937323aaf4821a94 | 163 | 165 | +2 |
  | 9514c72e81ae56cd | 1 | 1 | 0 |
  | 9b53ed9ac3d128c4 | 6 | 6 | 0 |
  | ba38dc7ef8434e18 | 324 | 457 | +133 |
  | cc198a82fcd36afa | 686 | 764 | +78 |
  | d817e29ab991764b | 989 | 1048 | +59 |
  | ee4df0cc3ec5f807 | 3387 | 3392 | +5 |
  | f49cc5feaea07ae6 | 13 | 13 | 0 |
  | f681f601165fe4e8 | 679 | 757 | +78 |
  | fbe54427b2bf7db0 | 94 | 94 | 0 |

  A rise is not proof. I read the 313 distinct new names. All are real
  declarations (`GetXxx`, `UpdateXxx`, `...FromDummy`, `NTAccount`, ...).
  Lost methods: 2 per RTTalentDB cache. Both are `new`, a false method from
  the target-typed expression `new("@EmpID", _user.UserID);` in
  `AssessmentResultService.cs` and `ResumeExperienceService.cs`. The new
  pattern no longer reads it as a method. No real method is lost in any
  system.
- Full suite: 1769 passed. `tests/test_search_roles.py` and
  `tests/test_sp_tables.py` fail at collection (`KeyError: 'PUR'`), with and
  without this change.
- Other cached systems keep the old scan until the service rescans them
  (cache v45 makes the old caches stale).
