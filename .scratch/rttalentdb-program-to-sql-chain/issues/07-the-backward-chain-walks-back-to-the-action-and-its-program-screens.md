# 07 — The backward chain walks back to the action and its Program Screens

**What to build:** A user asks "which screens does a change to this table
affect?" On an MVC system, the backward chain stops at the service method and
gives empty `ui_anchors`.

The backward chain uses the Bound Call Target edges in reverse. From the
method that reaches the table, it walks back to each controller action that
reaches that method. It then gives every Program Screen that holds the
action, with the strength of the screen-to-action link: determined for a
same-name action or a markup-layer View Anchor, and `likely` for a script URL
View Anchor. WebForms keeps its control event anchors.

Add a backward probe beside `compare_flow.py`. For each table of each called
stored procedure in `truth.json`, the probe checks that the backward chain
reaches the action and the view that `truth.json` gives.

See ADR-0044 and ADR-0019.

**Blocked by:** 05

**Status:** done (2026-10-07)

- [x] A table that `JobTypeService.InvalidateJobType` reaches gives the JobType
      action and its view in the backward chain
- [x] An action that two Program Screens hold gives both screens
- [x] A screen that reaches the action only through a script URL View Anchor
      has the strength `likely`
- [x] WebForms backward chain tests do not regress
- [x] The backward probe runs on RTTalentDB. Record its numbers in this ticket

## Result (2026-10-07)

`probes/backward_flow.py` on RTTalentDB (`probes/backward_after.json`):

```
tables asked 61 errors {} | other-Database tables left out 102
pairs (action, sp, table) 1637 | sp has a chain 1587 | action reached 883 (by a chain of that sp 865) | view in Views/{Controller} 864
actions with a table 227 | fully reached 120 | partial 6 | none 101
strengths {'determined': 645, 'likely': 290}
```

Baseline, the main directory service before this ticket
(`probes/backward_baseline.json`): action reached 0, fully reached 0.

The probe asks the backward chain for each table of each stored procedure that
a truth action calls. A pair passes when a stored procedure chain of the table
gives a Program Screen anchor of the action on `{Controller}Controller.cs`.
18 pairs pass through the chain of another procedure of the same table: the
chain of one method keeps the procedure of its first path only (see the notes).
`truth.json` gives no view, so the probe asserts the action only and counts the
pairs whose view is in `Views/{Controller}` (864).
The tables are the direct `reads` and `writes` of the procedure in the SQL
Execution Graph. A table of another Database (102) and a temporary table are
left out.

The 107 actions that are not fully reached fall into two groups:

- 81 have no forward chain (reach 0): no Program Screen holds the action
  (ADR-0019 scope). The forward probe has the same rows.
- 26 miss a pair whose stored procedure the forward chain also misses. These
  are the helper parameter paths (ADR-0020) and the `not_in_resolved_catalog`
  paths of ticket 05, both known reasons for ticket 09.

Per pair, the 754 misses are 667 pairs of the first group and 87 pairs of the
second. No pair misses for a reason of the backward chain alone. 114 actions
are fully matched in both directions.

Test suite in the worktree
(`pytest tests --ignore=tests/test_search_roles.py --ignore=tests/test_sp_tables.py`):
1805 passed, 2 failed (after the review fixes). The 2 failures are the known path-dependent tests
`test_program_refresh.py::test_refresh_does_not_write_wrapper_registry_or_system_catalog`
and `test_wrapper_decompilation.py::test_decompile_wrapper_classifies_sqlfunc_dll_end_to_end`.

WebForms check on STC (32 tables of the STC graph, backward before and after):
0 control event anchors lost, 12 gained. 16 tables now name another `method`
(see the deviation below).

## Implementation notes

- `program_screen.resolve_every_program_screen` gives one Program Screen per
  view, by the same controller and anchor rules as `resolve_program_screens`.
  `analyze_service._every_program_screen` adds the Razor Pages screens and
  leaves the page views out of the MVC set. The two input builders
  (`_razor_page_inputs`, `_mvc_screen_inputs`) now also serve
  `_program_resolutions`.
- `build_backward_chains` takes `program_screens`. It reverses the Bound Call
  Target edges (`_bound_call_graph(scan).edges`), walks back from the node of
  the chain method with no depth limit, and adds one `ui_anchors` entry for
  each screen that holds a reached action:

  ```
  {"kind": "program_screen", "file": "<view, relative>", "view": "<view name>",
   "controller_file": "<controller, relative>", "action": "<action>",
   "strength": "determined" | "likely"}
  ```

  A WebForms entry keeps its old shape and has no `kind`.
- A Shared view takes its controller by `_controller_of` (the one controller of
  its Area that declares an action of the view name). `resolve_program_screens`
  can reach a Shared view through a named controller instead. The backward set
  does not do that.
- **Different from the ticket text:** a stored procedure chain now names the
  method that holds the invocation (`caller_class.caller_method`) in `class`
  and `method`, not the entry method. The reason is the one of ticket 05: on
  RTTalentDB the entry method of every service path is the primary
  constructor (`JobTypeService.JobTypeService`). The chain key is
  `(file, class, method)`, and spec-rag `_merge_backward_chains` dedupes by
  `(file, method, sp_name, via)`. With the entry method, the paths of two
  service methods with the same last procedure merged into one chain, and the
  screens of the second method were lost. `entry_method` stays in the chain.
  The WebForms control event search still starts from the entry method too,
  so no WebForms anchor is lost.
- One method that reaches a table through two stored procedures still gives
  one chain, with the procedure of its first path. This is the old behaviour,
  and the spec-rag merge documents it. Its screens are the same for both
  paths.
- Not in this ticket: spec-rag `_render_backward_chains`
  (`impact_orch/agent_tools.py`) prints each anchor as
  `control id (event=handler)`. A `program_screen` entry has none of these
  keys, so the agent sees an empty line for it. The renderer needs a branch on
  `kind`.

## Code review (2026-10-07, `/code-review` on d5f9b7b)

Fixed:

- Standards: `_reverse_method_adjacency` repeated the body of the new
  `_reverse_edges`. It now calls it.
- Standards: the chain read `caller_class` and `caller_method` a second time
  beside `_caller_node`. Both now use `_caller_names`.
- Standards: `_every_program_screen` rebuilt the Razor page names and sent them
  back one by one. `program_screen.resolve_every_razor_page_screen` now gives
  them, beside `resolve_every_program_screen`.
- Standards: some new docstrings used "screen" alone (CONTEXT.md: avoid). They
  now say Program Screen.
- Spec: a path with `caller_method` and no `caller_class` gave the node
  `.Method`, which joins no edge. `_caller_names` now takes the class of the
  entry method. The forward chain uses the same function.
- Spec: new tests for a Razor Pages handler, for a Program Screen that names one
  action in markup and in a script URL (`determined` wins), and for a WebForms
  chain that names the holding method and keeps the control event of its entry
  method.
- Spec: the probe counted a pass through the chain of another procedure without
  saying so. It now gives that count (18), and the pair-level miss reasons are
  in the Result.

Not changed:

- Standards: the WebForms control event search still matches the call text in
  one file (`_ancestors_of`, depth 8). ADR-0044 is about the call graph. The
  ticket says "WebForms keeps its control event anchors", so this ticket keeps
  that search as it was and only adds the entry method as a second start.
- Standards: `_razor_page_inputs` and `_mvc_screen_inputs` return a dict for
  `**`. The keys are the keyword names of the resolvers, and mypy shows no new
  error.
- Spec: a Shared view reached through a named controller (see the notes).
- Spec: the `class`/`method` deviation and the spec-rag renderer. See the notes.
  The user decides on the renderer.
