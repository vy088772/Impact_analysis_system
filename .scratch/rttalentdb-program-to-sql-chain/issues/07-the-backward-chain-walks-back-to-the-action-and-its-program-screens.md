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

**Status:** ready-for-agent

- [ ] A table that `JobTypeService.InvalidateJobType` reaches gives the JobType
      action and its view in the backward chain
- [ ] An action that two Program Screens hold gives both screens
- [ ] A screen that reaches the action only through a script URL View Anchor
      has the strength `likely`
- [ ] WebForms backward chain tests do not regress
- [ ] The backward probe runs on RTTalentDB. Record its numbers in this ticket
