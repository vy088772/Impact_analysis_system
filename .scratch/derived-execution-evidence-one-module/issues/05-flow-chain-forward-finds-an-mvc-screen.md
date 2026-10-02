# 05 — `/flow_chain` forward finds an MVC screen

**What to build:** `/flow_chain` in the forward direction resolves the program name through the same Program Screen resolution as `/analyze`. It applies action ownership. An MVC screen such as RTTalentDB `JobDutyMtn` then gets a forward chain. A reading of the code found this defect, so the work starts with a test that proves it. See the spec, sections "Endpoints" and "Testing Decisions".

**Blocked by:** 02 — `/path_evidence` gets its evidence from the module and finds a path by its path_id.

**Status:** resolved (2026-10-02)

- [x] First, an endpoint-seam test on the `JobDutyMtn` Program Screen fixture expects a forward chain. It fails before the fix. If it passes, stop and report.
- [x] Forward uses the same program resolution helper as `/analyze`.
- [x] When one name resolves to several screens, forward merges their files and actions and builds one chain.
- [x] When the anchor method is not an owned action, forward returns no chain.
- [x] Forward gives the module the files of the resolutions as the needed files.
- [x] The response shape does not change.
- [x] A WebForms program gives the same forward chain as before.
- [x] After the fix, one run against the real RTTalentDB returns a forward chain for `JobDutyMtn`. Record the result in this ticket under Comments.

## Comments

### Implementation Notes (2026-10-02)

- Affected functions: `flow_chain` (forward branch) and `build_forward_chain`.
- User-visible change: an MVC screen such as `JobDutyMtn` now gets a forward chain. An anchor that is not an action of the screen still gives no chain.
- The first test failed before the fix with `forward_chain=None`. The defect is confirmed.
- Forward calls `_program_resolutions_for_names`, the same helper as `/path_evidence`. It wraps `_program_resolutions`, which `/analyze` also uses.
- `build_forward_chain` takes an optional `owns_action`. The default accepts every method, so a WebForms program keeps its previous behaviour.
- With a Database, forward asks the evidence source for the files of the resolutions. It keeps the invocations that a resolution owns, so an action of another screen on a shared controller does not join the chain. A helper, `_invocation_owner`, now serves both forward and `/path_evidence`.
- Without a Database, forward does not call the evidence source. This is the previous behaviour.
- New tests: `tests/test_flow_chain_forward_program_screen.py` (6 tests). They cover the MVC chain, the needed files and the refresh flag, a foreign anchor, several screens of one name, an action of another screen, and a WebForms page in a repository with views.
- Focused tests: 148 passed across the forward, backward, evidence, Program Screen, and path evidence test files.
- Full suite: 1627 passed (1621 before this ticket). Two collection errors remain in `test_search_roles.py` and `test_sp_tables.py`. They need ODBC Driver 17 for SQL Server.
- Typecheck: 281 mypy errors in the two changed modules and their imports, before and after. No new errors.
- Standards and Spec reviews found one duplicated block. It is now the shared `_invocation_owner` helper. The Spec review also read the new anchor check as a tightening. It is not: the old adjacency test and the declared-method test were the same test, so only ownership is new.

### Real RTTalentDB run (2026-10-02)

- Source: the cached scan of `System_Dept_1/RTTalentDB` (381 C# files, 133 views). `JobDutyMtn.cshtml` and `JobDutyController.cs` are both in it.
- Request: `/flow_chain`, forward, program `JobDutyMtn`, anchor `JobDutyMtn`, no Database.
- Result: `forward_chain` is not `None`. `method_path` is `['JobDutyMtn']`.
- Request with the anchor `NoSuchAction`: `forward_chain` is `None`.
- No SQL cache for an RTTalentDB Database exists in this environment. So the run has no stored procedure chain. The tests cover that part with fixed evidence.
