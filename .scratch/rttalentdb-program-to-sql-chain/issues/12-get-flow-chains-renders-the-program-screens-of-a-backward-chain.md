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

**Status:** ready-for-agent

- [ ] A `program_screen` anchor renders its view, its action, its controller
      and its strength
- [ ] A `likely` anchor reads as a candidate in the rendered text
- [ ] A WebForms anchor renders the same line as before
- [ ] A chain with no anchor keeps its current "no UI" line

**Notes:**

- Source: ticket 07 (2026-10-07). The user chose to fix the renderer in a new
  ticket and not to defer it to ticket 09.
- The change is in the spec-rag repository only. The Impact response does not
  change.
- `rag_client._merge_backward_chains` dedupes by `(file, method, sp_name,
  via)`. It keeps `ui_anchors` as they are, so it needs no change.
