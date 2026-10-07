# 12 — `get_flow_chains` renders the Program Screens of a backward chain

**What to build:** Since ticket 07, a backward chain on an MVC system gives
one `ui_anchors` entry for each Program Screen that holds a reached action:

```
{"kind": "program_screen", "file": "<view, relative>", "view": "<view name>",
 "controller_file": "<controller, relative>", "action": "<action>",
 "strength": "determined" | "likely"}
```

The spec-rag tool `get_flow_chains` renders a backward chain with
`_render_backward_chains` (`llamaindex-spec-rag/impact_orch/agent_tools.py`).
It prints each anchor as `對應 UI：{control} {id}（{event}={handler}）`. A
`program_screen` entry has none of these keys, so the agent sees the empty
line `對應 UI：  （=）`. The user does not see which Program Screens a table
change affects.

Render an anchor by its `kind`. A WebForms entry has no `kind` and keeps its
current line. A `program_screen` entry gives the view, the action with its
controller, and the strength. A `likely` strength must read as a candidate,
not as a fact (ADR-0019: a script URL only looks like a call).

See ticket 07 (Implementation notes) and ADR-0019.

**Blocked by:** None. Ticket 07 is done.

**Status:** done

- [x] A `program_screen` anchor renders its view, its action, its controller
      and its strength
- [x] A `likely` anchor reads as a candidate in the rendered text
- [x] A WebForms anchor renders the same line as before
- [x] A chain with no anchor keeps its current "no UI" line

**Notes:**

- Source: ticket 07 (2026-10-07). The user chose to fix the renderer in a new
  ticket and not to defer it to ticket 09.
- The change is in the spec-rag repository only. The Impact response does not
  change.
- `rag_client._merge_backward_chains` dedupes by `(file, method, sp_name,
  via)`. It keeps `ui_anchors` as they are, so it needs no change.

## Implementation notes

- Done 2026-10-07 in the spec-rag repo only. New helper
  `_render_backward_anchor` in `impact_orch/agent_tools.py`; it renders by
  `kind`. `program_screen` line: `對應 Program Screen：{view}（action, controller, strength=…）`.
- A `likely` anchor adds a "候選" warning: a script URL only looks like a call.
- A WebForms anchor and the "no UI" line are unchanged.
- Tests: `tests/test_backward_chain_program_screen_render.py` (5 tests).
- Full suite: 1628 pass. `test_sql_cache_fixtures.py::test_the_format_versions_are_the_sample_versions`
  fails before and after this change (not caused by it).
