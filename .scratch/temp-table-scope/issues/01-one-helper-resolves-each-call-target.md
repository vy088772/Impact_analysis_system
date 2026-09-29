# 01: One helper resolves each call target

**What to build:** The graph builder decides whether a calls relationship names
a module that the graph defines in one helper. The graph that the builder
returns does not change. Ticket 04 and canonical-object-identity Step 2b each
change the call target rule in this one helper only.

See "Call visibility" in the spec.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] One helper takes a call target and returns the module node that the graph defines for it, or nothing.
- [ ] Every site that turns a call target into a module node identity uses the helper.
- [ ] The helper keeps the existing `dbo` fill and its Step 2b comment. The rule does not change.
- [ ] The graph format version does not change.
- [ ] Every existing graph test passes with no edit.
- [ ] The whole suite of this repository passes.
