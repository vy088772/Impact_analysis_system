# The Call Graph Follows the Bound Target of Each Call

**Status:** Accepted
**Date:** 2026-10-07

## Context

[ADR-0019](0019-a-program-is-one-view-plus-the-actions-that-serve-it.md) decides which actions belong to a Program Screen. It says nothing about the methods that those actions call.

The flow chain builds its call graph only from the files of the program. For an MVC program, those files are the view and the controller. An action that calls `_service.InvalidateJobType(...)` therefore stops at the controller, because `Services/MS/JobTypeService.cs` is not in the graph. The graph also links a call only by its bare method name, and the scan records the call text `_service.InvalidateJobType`. The receiver `_service` has the interface type `IJobTypeService`, and nothing resolves it to `JobTypeService`.

On RTTalentDB, 0 of 227 actions reach their stored procedures through the forward chain. The SQL side is complete for 162 of the 163 called procedures. The gap is in the C# call graph only.

`expand_related_programs` in `/analyze` has the same gap. It skips a call when the qualifier is not a class name and the method name has two or more declarations. An interface and its implementation give two declarations.

## Decision

### Scope

ADR-0019 limits the entry actions of a Program Screen. It does not limit the callees. From an entry action, the call graph follows each call into any file of the scan root.

The call graph follows only the methods that a call reaches. It does not add the other methods of the callee class. A shared service, such as `IUtilityService` in 15 RTTalentDB controllers, adds to a screen only the methods that the screen calls.

### Bound Call Target

The analyzer host records the Bound Call Target of each call. The host uses the semantic model, so it resolves fields, primary constructor parameters, properties, local variables, and overloads. When the bound method belongs to an interface, the host resolves the interface through the Local Implementer rule. The call graph uses the Bound Call Target. It does not use the call text.

When no Local Implementer exists, or when two or more exist, the branch stops at that call. The chain reports the call and the reason in its `diagnostics`. It does not guess an implementation.

### Depth

The reachable set has no depth limit. A visited set stops each cycle. A node is one bound method, so two methods with the same name in different classes stay two nodes.

### Backward direction

The backward chain uses the same edges in reverse. From a service method, it walks back to each controller action that reaches it. It then gives every Program Screen that holds that action, with the strength of the screen-to-action link: determined for a same-name action or a markup-layer View Anchor, and `likely` for a script URL View Anchor.

### One edge source

`expand_related_programs` uses the same Bound Call Target edges. It keeps its own `depth` and `max_programs` limits.

## Considered Options

- **Amend ADR-0019.** ADR-0019 records what a program is. The callee rule is a different decision, so it gets its own record.
- **Add the whole callee class.** This pushes every method of a shared service into every screen that injects it. ADR-0019 calls that result noise.
- **Resolve the receiver type in Python.** The Python side would need a second copy of the Local Implementer rule. It would also need its own resolution of fields, properties, local variables, and overloads. The two copies would drift.
- **Follow every implementer of an ambiguous interface.** This guesses, and the Local Implementer rule forbids a guess.
- **A fixed depth limit.** A chain such as action → service → helper service → stored procedure is common. A fixed limit cuts it.

## Consequences

- The scan format adds the Bound Call Target. The C# scan cache version rises, and each system needs a local rescan.
- On an MVC system, mode 4 `flow_chain` reports stored procedures, tables, and `ui_anchors`. It reported none before.
- `/analyze` reports service files in `related_programs` where it reported none before.
- The acceptance measure for RTTalentDB is 227 of 227 actions fully matched, except a named list of misses with a reason for each. Known reasons are a helper parameter ([ADR-0020](0020-wrapper-command-text-is-traced-inside-one-method-only.md)), an ambiguous implementation, and Unresolved Dynamic SQL. The backward direction gets the same measure with the same list.
