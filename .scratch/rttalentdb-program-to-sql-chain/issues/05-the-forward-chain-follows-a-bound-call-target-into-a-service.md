# 05 — The forward chain follows a Bound Call Target into a service

**What to build:** A forward chain from an MVC action reaches the stored
procedures that its service methods call. Today 0 of 227 RTTalentDB actions
reach a stored procedure, because the call graph matches bare method names
inside the program files only.

The analyzer host records the Bound Call Target of each call, with an
interface method resolved through the Local Implementer rule. The record goes
through the gateway into the scan and the C# scan cache. The forward chain
uses these edges and does not use the call text. A node is one class-qualified
method, so two methods with the same name in different classes stay two
nodes. An execution path joins the chain by its full entry method, not by the
last name segment. The reachable set has no depth limit, and the visited set
stops each cycle.

The change applies to WebForms too. The chain no longer matches the call text
in any framework.

See ADR-0044 and the Answer of ticket 03.

**Blocked by:** None — can start immediately.

**Status:** done (2026-10-07). One ADR-0044 conflict is open: see the overload note below.

- [x] The host reports a Bound Call Target for a call through a field, a
      primary constructor parameter, a property and a local variable
- [x] A call through an interface with one Local Implementer binds to the
      implementer's method
- [x] The forward chain of the RTTalentDB JobType action reaches the stored
      procedure that `JobTypeService.InvalidateJobType` calls
- [x] `compare_flow.py` on RTTalentDB gives more than 0 fully matched actions.
      Record the new numbers in this ticket
- [x] A service that calls another service (for example through
      `IUtilityService`) contributes the second service's stored procedures
- [x] Two methods with the same name in two classes do not merge into one node
- [x] The C# scan cache version rises, and a rescan of RTTalentDB uses the new
      format
- [x] WebForms flow chain tests and the impact suite baseline do not regress

**Notes:**

- Feedback loop: the commands in ticket 03.
- The impact suite has 3 path-dependent tests that differ between a worktree
  and the main directory. They are not a regression.
- After the cache version rises, rescan locally. An old scan cache makes each
  system skip.
- The case of zero or two or more implementers belongs to ticket 06. In this
  ticket, the branch can stop there without a report.

## Result (2026-10-07)

`compare_flow.py` on RTTalentDB, scan cache v46 (`probes/flow_after.json`):

```
called 261 errors {}
actions that should reach SP 227 | fully matched 114 | partial 6 | none 107
extra SPs not in truth 62
reachable_methods == 1 (stops at action): 123 of 261
SP coverage 110 / 163
```

Baseline: fully matched 0, SP coverage 0 / 163.

The 113 actions that are not fully matched fall into two groups:

- 87 have no forward chain (reach 0). The Program Screen does not own the
  action (ADR-0019 scope). The baseline has the same 104 rows at reach 0.
  This ticket does not change the scope.
- 26 reach the service method, but the path is `command_text_method_parameter`
  (a helper parameter, ADR-0020). 6 of them also have a
  `not_in_resolved_catalog` path. Both are known reasons for ticket 09.

The rescan found 589 calls in RTTalentDB. 588 have a Bound Call Target. One
call is `ambiguous_implementation`: `strategy.BuildViewModelAsync`, with the
candidates `EmptyResumeStrategy`, `ResumeResumeStrategy` and
`ResumeTraditionStrategy` (ticket 06).

Test suite in the worktree
(`pytest tests --ignore=tests/test_search_roles.py --ignore=tests/test_sp_tables.py`):
1789 passed, 2 failed. The 2 failures are
`test_program_refresh.py::test_refresh_does_not_write_wrapper_registry_or_system_catalog`
and `test_wrapper_decompilation.py::test_decompile_wrapper_classifies_sqlfunc_dll_end_to_end`,
two of the 3 known path-dependent tests that fail in a worktree.

WebForms check on real roots:

- STC (project compilation available): 150 calls, 150 bound.
- TTRDQ (`unavailable_reference_resolution_failed`, so the source-only
  compilation): 281 files, 1289 calls, 1289 bound. Of the 942 same-file edges
  that the old call-text rule gave, the new edges keep 941. The one that is
  gone is `DocIssue.Page_Load -> checkPart`. It came from the JavaScript string
  `"checkPart('" + ... + "')"`, so it was a false edge.

## Implementation notes

- Host: `tools/StaticAnalyzerHost/BoundCallAnalyzer.cs` binds each
  `InvocationExpressionSyntax` with the semantic model. Each method span in the
  host output has a `calls` list. A call into a framework or package method
  is not recorded. The Local Implementer rule is the one in `WrapperAnalyzer`
  (`ResolveLocalImplementers` now has an internal overload by interface name).
  The candidate also names the class that declares the method, so an
  implementer that inherits the method from a corpus base binds to the base.
- A scan root with no available project compilation (most WebForms systems)
  binds its calls in a source-only compilation of the same trees, with the
  runtime's own assemblies. The wrapper analysis still gets `null` there, so
  its ratings do not change.
- **Different from the ticket text:** the record does not go through
  `CSharpAnalysisGateway`. It goes from the host through
  `ProjectScanResult.capture_source_snapshot` into `MethodSourceSpan.calls`
  (`CallSite`), and so into the scan cache. The gateway rates Database
  Invocations only, and a Bound Call Target has no evidence to rate. The
  Python host adapter passes the record on unchanged. The cache version is 46.
- A node is `Class.Method` (`code_analyzer.models.call_graph_node`) with the
  simple class name, the same key that Database Invocations and table
  relations carry.
- **Open, ADR-0044 conflict:** the ADR says "A node is one bound method". The
  ticket says "one class-qualified method". The code follows the ticket, so the
  overloads of one method share one node, and a call to one overload reaches
  the stored procedures of all of them. A node per overload needs a signature
  on each method span, each call target and each Database Invocation; a
  Database Invocation now carries only the method name. Two classes with one
  simple name in two namespaces also share one node. A method of a `record`
  or a `struct` has the class `""` in its span, so a call into it gives no edge.
- The host also gives `ambiguous_overload` when the candidate symbols of one
  call name two or more classes. ADR-0044 names only the two Local Implementer
  cases. The chain stops the branch there too. Ticket 06 must report it or
  remove it.
- **Different from the ticket text:** an execution path joins the chain by the
  method that holds its invocation (`caller_class.caller_method`), not by
  `entry_method`. The entry method is the outermost caller of a same-file chain
  that `_method_chain_for_file` builds from the call text. On RTTalentDB the
  regex parser reads a primary constructor `JobTypeService(` as a method, so the
  entry method of every service path is `JobTypeService.JobTypeService`, which
  no action reaches. ADR-0044 forbids the call text as an edge, and the call
  graph already reaches each caller, so the holding method is the join key.
  The join still uses the full class-qualified method, not the last segment.
- `/flow_chain` forward rates the files that declare a reached node
  (`files_of_nodes`), not only the program files, and keeps an invocation when
  its holding method is a reached node.
- `reachable_methods` and `method_path` still give bare method names. The
  spec-rag `get_flow_chains` tool adds `reachable_methods` to its scope by name.
- The backward chain still uses `_method_adjacency` (call text). Ticket 07
  moves it to the Bound Call Target edges.
- An incremental refresh of one file computes its calls against the whole
  scan root. A change to another file (for example a second implementer) does
  not update the calls of the unchanged files until a full rescan.
- `probes/compare_flow.py` read each stored procedure as a string. A forward
  chain entry is a dict, so the probe now reads its `name`. The baseline run
  never had an entry, so it never met the dict.
- The test fixture `_controller_result` named the class of `Alpha.aspx.cs`
  `Alpha.aspx`. A real code-behind class is `Alpha`, and the node key needs the
  real name. Two expected values in `test_analyze_evidence_source.py` follow.

## Code review (2026-10-07, `/code-review` on b2603e4)

Fixed:

- Standards: the `Class.Method` key was built in seven places. It is now one
  function, `call_graph_node`.
- Standards: `/flow_chain` computed the reach twice. `build_forward_chain` now
  takes the `reach` that the endpoint already has.
- Standards: `forward_reach` had a default `owns_action` that no caller used.
- Spec: the WebForms and suite results were not in this ticket. They are now.
- Spec: the gateway deviation was not marked. It is now.

Not changed:

- Standards: "the chain reports the call and the reason in its `diagnostics`"
  (ADR-0044). This ticket defers that to ticket 06. The host already records
  `unresolved_reason` and `candidate_classes`, so ticket 06 needs no rescan.
- Spec: the overload node, the simple class name, `ambiguous_overload` and the
  stale calls after an incremental refresh. See the notes above.
- Spec: a path with no `caller_method` still joins. Every path that
  `build_execution_paths` makes has one, and the endpoint filters the
  invocations by the reach first.
