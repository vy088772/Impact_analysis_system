# 18 — Whole-chain code review fixes

**What to build:** Fix the findings of the two-axis code review of
`ae7a5e6...a49f9c7` (tickets 01–17, ADR-0044). The user chose option A for the
ADR conflict: record the WebForms exception in ADR-0044, keep the behavior.

**Blocked by:** None.

**Status:** done (2026-10-08)

## Findings and fixes

Standards axis:

- [x] ADR conflict: the backward chain finds WebForms control events by call
      text, with a depth limit of 8. ADR-0044 now has a **WebForms control
      events** section. `build_backward_chains` and `add_chain` point to it.
- [x] One Local Implementer whose method does not map to the interface method
      reported `no_local_implementer`. The host now reports
      `unmapped_implementation`, with the implementer as its one candidate
      class. The backward chain lists such a call in `diagnostics` when the
      implementer is a reached class.
- [x] The `CallSite` docstring named only `ambiguous_implementation` for
      `candidate_classes`. It now names all three reasons that fill it.
- [x] Middle Man: `CallSite.bound_target` is removed. Callers read
      `target_node`.
- [x] Duplicated Code: a forward `/flow_chain` built `MethodNodes` four times.
      `ForwardReach` now carries its `method_nodes` and gives `files(scan)`.
      `files_of_nodes` is removed. The backward chain passes its one
      `MethodNodes` to `_screen_anchors_by_node`. (`bound_call_edges` and
      `forward_reach` run in two different requests, so each request builds
      the call graph once.)
- [x] Duplicated Code: the three `controller, action` anchor blocks in
      `razor_parser.py` share `_controller_action_anchor`.
- [x] Primitive Obsession: `ActionEntry` is `Tuple[str, str]` only. No caller
      passed a `str`.
- [x] Output argument: `build_backward_chains` returns `BackwardChains(chains,
      diagnostics)`. The handler adds the diagnostics to its own list.
- [x] Style: the new docstrings and comments in `flow_chain_builder.py` are in
      Chinese, as the rest of the module. Ticket numbers are removed from
      production code.

Spec axis:

- [x] 1, 5, 6: ADR-0044 (WebForms section, the strength sentence, the
      `unmapped_implementation` reason) and the glossary entry **Bound Call
      Target** (one target for each candidate overload, the WebForms
      exception).
- [x] 2, 3: ticket 15 records the view-folder fallback and the script cache.
- [x] 4: ticket 13 records the comment stripping.
- [x] 7: `Url.Action("A", variable)` gives no anchor. The glossary entry
      **View Anchor** says so.
- [x] 8: ticket 11 checklists are ticked.
- 9: no change needed.

## Result

- Scan cache version 51 -> 52 (the host reason). Rescan locally.
- New tests: `test_one_local_implementer_with_no_matching_method_names_that_implementer`,
  `test_an_unmapped_implementation_call_appears_in_the_backward_diagnostics`,
  `test_an_url_action_call_with_a_variable_second_argument_gives_no_anchor`.

## Code review follow-up (2026-10-08)

The two-axis review of the first commit found these. All are fixed:

- The `URL_HELPER_PATTERN` lookahead also dropped `Html.BeginForm("A", null,
  FormMethod.Post)`, `@"C"` and named arguments. `null` and a named argument
  such as `values:` now name no controller. `@"C"` and `controllerName: "C"`
  name one. A variable still gives no anchor. Four new tests. The 1357 helper
  calls of the cached systems still give the same result, so the v52 rescan
  stays valid.
- **Local Implementer** in the glossary said that the class "itself declares
  the invoked method", so a class with no mapped method was not one. The entry
  now says that the search compares names, and names `unmapped_implementation`.
- The ADR-0044 WebForms section said "only inside the code-behind file". The
  search compares file names, not folders, and also reads `.ascx`. The section
  now says so, and names the false match of two pages with one file name.
- ADR-0044: an `unmapped_implementation` call gives an entry when any method
  of its implementer is reached.
- The `CallSite` docstring states that `ambiguous_overload` candidates are
  containing types (a class or an interface). `ForwardReach.files` states
  that `scan` must be the scan of the reach.
