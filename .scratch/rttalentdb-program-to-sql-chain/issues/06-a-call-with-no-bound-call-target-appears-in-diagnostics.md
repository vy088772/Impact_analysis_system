# 06 — A call with no Bound Call Target appears in diagnostics

**What to build:** When a call has no Bound Call Target, the forward chain
stops that branch and tells the user why. A user who sees no stored
procedure can then tell "no database access" from "the analysis could not
follow this call".

Two cases give no Bound Call Target: an interface with no Local Implementer,
and an interface with two or more (`ambiguous_implementation`). The chain
does not guess an implementation. The chain `diagnostics` lists the caller
method, the call, and the reason. For `ambiguous_implementation`, it names
every candidate class.

See ADR-0044.

**Blocked by:** 05

**Status:** in-progress (2026-10-07)

- [x] A call through an interface with no Local Implementer appears in
      `diagnostics` with its reason
- [x] A call through an interface with two Local Implementers appears in
      `diagnostics` as `ambiguous_implementation` and names both classes
- [x] The chain does not follow either implementer of an ambiguous interface
- [x] The RTTalentDB interface with two implementers appears in the
      `diagnostics` of each action that calls it

**Notes:**

- The host has recorded the reason and the candidate classes since ticket 05,
  so this ticket needed no new scan format and no rescan.
- A `diagnostics` entry of this kind:

  ```
  {"kind": "unresolved_call", "caller": "ResumeService.GetResumeDynamicViewModel",
   "call": "strategy.BuildViewModelAsync", "reason": "ambiguous_implementation",
   "unresolved_reason": "ambiguous_implementation",
   "candidate_classes": ["EmptyResumeStrategy", "ResumeResumeStrategy", "ResumeTraditionStrategy"],
   "source_span": {"relative_path": "...", "start_offset": ..., "end_offset": ...}}
  ```

  `reason` and `unresolved_reason` hold the same value, because the unproven
  execution paths in the same list carry both names. `kind` tells the two
  sorts of entry apart.
- Only the calls of reached methods appear. A call with no target in a method
  that the action does not reach stays out.
- The host also gives `ambiguous_overload` (ticket 05). It appears here the
  same way, with the candidate classes.
- RTTalentDB result (2026-10-07): the interface is `IResumeStrategy`, with
  three Local Implementers. Two truth actions reach
  `ResumeService.GetResumeDynamicViewModel`: `Home.HomePage` and
  `ResumeQuery.GetResumePartial`. Both report the call. No other action
  reports it. `compare_flow.py` gives the same numbers as ticket 05
  (114 fully matched).
- Not in this ticket: the spec-rag `get_flow_chains` tool
  (`impact_orch/agent_tools.py::_render_forward_chain`) does not render the
  forward chain `diagnostics`. So the user does not yet see this text in an
  answer. `rag_client._merge_forward_chains` already keeps the entries.
