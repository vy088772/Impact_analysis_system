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

**Status:** ready-for-agent

- [ ] The host reports a Bound Call Target for a call through a field, a
      primary constructor parameter, a property and a local variable
- [ ] A call through an interface with one Local Implementer binds to the
      implementer's method
- [ ] The forward chain of the RTTalentDB JobType action reaches the stored
      procedure that `JobTypeService.InvalidateJobType` calls
- [ ] `compare_flow.py` on RTTalentDB gives more than 0 fully matched actions.
      Record the new numbers in this ticket
- [ ] A service that calls another service (for example through
      `IUtilityService`) contributes the second service's stored procedures
- [ ] Two methods with the same name in two classes do not merge into one node
- [ ] The C# scan cache version rises, and a rescan of RTTalentDB uses the new
      format
- [ ] WebForms flow chain tests and the impact suite baseline do not regress

**Notes:**

- Feedback loop: the commands in ticket 03.
- The impact suite has 3 path-dependent tests that differ between a worktree
  and the main directory. They are not a regression.
- After the cache version rises, rescan locally. An old scan cache makes each
  system skip.
- The case of zero or two or more implementers belongs to ticket 06. In this
  ticket, the branch can stop there without a report.
