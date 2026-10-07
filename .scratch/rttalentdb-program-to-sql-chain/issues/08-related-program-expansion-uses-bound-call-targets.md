# 08 — Related program expansion uses Bound Call Targets

**What to build:** `/analyze` with an expand depth above 0 lists the files
that a program calls into. For RTTalentDB JobType it gives
`related_programs: []`, because the expansion matches a call by method name
and skips a name with two declarations. An interface and its implementation
give two declarations.

The expansion uses the same Bound Call Target edges as the flow chain. It
keeps its `depth` and `max_programs` limits. The project then has one rule for
"which method does this call reach".

See ADR-0044.

**Blocked by:** 05

**Status:** done (2026-10-07)

- [x] `/analyze` for RTTalentDB JobType with expand depth 1 lists
      `JobTypeService` and the called method
- [x] A WebForms static helper call (such as `CommonFunction.AlertMsg`) still
      appears in the expansion
- [x] Two methods with the same name in two classes do not both appear for
      one call
- [x] The `depth` and `max_programs` limits behave as before

**Notes:**

- The old `[]` for JobType had two causes. The ticket names the first: the
  expansion skipped a method name with two declarations. The second:
  `/analyze` kept an entry only when `owns_method(called_by)` was true, and
  `called_by` is `File.Method` (`JobTypeController.JobTypeInvalid`). That never
  matches a bare action name, so a Program Screen lost every entry. Now
  `owns_action` selects the start methods, and the filter after the expansion
  is gone. The callees have no ownership check (ADR-0019 and ADR-0044 Scope).
- **Different from the ticket text:** "The `depth` and `max_programs` limits
  behave as before" is true for the limits. But a level now holds less. The old
  code put each reached file into the next level, so depth 2 walked every
  method of that file. The new code walks only the method that a call reaches,
  as ADR-0044 Scope says ("It does not add the other methods of the callee
  class"). The ADR is the primary record, so the code follows it.
- A new rule: a call into the same file (or into a file of the program) is not
  listed and costs no level. The expansion walks its calls at the same level.
  The old code got the same result because it walked each whole file.
- `called_by` keeps its old shape: the file name without its last extension,
  plus the method (`ApprovalQry.aspx.btnApprove_Click`). spec-rag shows it as is.
- The edges come from `flow_chain_builder.bound_call_edges`, a new public
  function over `_bound_call_graph`. The declarations come from
  `csharp_results`. A node that no file declares (for example a `record`
  method, class `""`) lists nothing.
- The constructor filter (`m.name == cls.name`) is gone. The host binds only
  `InvocationExpressionSyntax` with `MethodKind.Ordinary`
  (`BoundCallAnalyzer.cs`), so a constructor is never a Bound Call Target.

## Result (2026-10-07)

Worktree service on port 8802 with the shared scan cache, probed from
spec-rag (`rag_client.analyze`, `include_snippets=False`). Port 8800 is the
main directory before this ticket.

- RTTalentDB JobType, depth 1: 8800 gives `[]`. 8802 gives 9 entries: 8 in
  `Services/MS/JobTypeService.cs` (among them `InvalidateJobType <-
  JobTypeController.JobTypeInvalid`) and `ModelStateExtensions.GetErrors`.
- Depth 2 gives the same 9. `JobTypeService` calls only
  `_context.usp_ExecCmd...`, which a package declares, not the code.
- Depth 2 with `max_programs` 3 gives the first 3 entries.
- STC ApprovalQry (depth 1), UserEdit and TransactionApp (depth 2): the same
  output on 8800 and 8802, with `CommonFunction.AlertMsg` in each.
- TTRDQ has no repo in the catalog, so `/analyze` answers 400. Not probed.

Test suite in the worktree
(`pytest tests --ignore=tests/test_search_roles.py --ignore=tests/test_sp_tables.py`):
1805 passed, 2 failed. The 2 failures are the known worktree path-dependent
tests (`test_program_refresh.py::test_refresh_does_not_write_wrapper_registry_or_system_catalog`,
`test_wrapper_decompilation.py::test_decompile_wrapper_classifies_sqlfunc_dll_end_to_end`).

## Code review (2026-10-07, `/code-review` on 34198a2)

Fixed:

- Standards: the frontier and the declarations were bare 3-tuples. They are
  now `_Caller` and `_Declaration`.
- Standards: `walked` and `listed` are now `queued_nodes` and `reported`.
- Standards: `bound_call_edges` now says why it leaves out `unresolved_calls`.
- Spec: the second cause, the depth change and the review were not in this
  ticket. They are now.

Not changed:

- Standards: the start-node loop has the same shape as the one in
  `forward_reach`. Ticket 07 changes `flow_chain_builder.py` at the same time,
  so a shared helper waits until both tickets are merged.
- Spec: the edges (`source_snapshots`) and the declarations (`csharp_results`)
  join on `call_graph_node`. A class name that differs between the two drops
  the entry. This is in the tolerance of the tool.
