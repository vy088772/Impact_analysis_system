# A Command Factory's Connection Gains a Third Connection Behavior Boundary Value

**Status:** Accepted
**Date:** 2026-09-14

## Context

Ticket 06 widened the Command Source record so a construct with no command object and no
bound variable could be added as one further rule, without a change to the classification
flow around it. `SQLDbContext.usp_ExecCmdGetDataSetAsync` and two sibling methods already
exercise the shape that prefactor was built for: each obtains its command through
`Database.GetDbConnection().CreateCommand()`, a factory call, never a `new` construction.

The Connection Behavior Boundary resolver reads a connection from two places only: the second
argument of a command constructor, and a `Connection` property assignment. A factory call
gives neither — the connection is the *receiver* of the factory call (`Database.GetDbConnection()`
here), and the resolver never read that receiver. Measured against the real shared
`CommonLibrary.dll`, all three classified `SQLDbContext` methods therefore reported an empty
boundary and failed the behaviour surface completeness check with
`connection_behavior_boundary_missing`. Tickets 01, 02 and 04 together still left the Contract
refused for exactly this reason.

The obvious first fix is to read the factory receiver and report `wrapper_connection` — the
value a Field-Held Connection already produces for every other rule. That is correct for a
receiver like `conn` in `SqlConnection conn = new SqlConnection(cn); conn.CreateCommand();`:
the wrapper genuinely holds that connection, and every caller reaches whatever database it
opens. It is not correct for `Database.GetDbConnection()`. `SQLDbContext` is the shared base
class behind five Systems and many derived context types; `Database` is Entity Framework
Core's own per-context facade, and the connection it opens follows the *derived* context
type's own registration — `AddDbContext<T>(... GetConnectionString("Key") ...)`, the shape
this analyzer already names Context Connection Registration — not any connection
`SQLDbContext` itself holds. Reporting `wrapper_connection` here would claim a single fixed
connection for a Contract shared by five Systems, none of which exists at that scope.

## Decision

The Connection Behavior Boundary vocabulary gains a third value, `context_connection`, kept
distinct from `wrapper_connection` rather than folded into it:

- The connection resolver's new command-factory rule runs last, only when the
  constructor-argument rule and the `Connection` property-assignment rule both resolve
  nothing. An already-resolved boundary therefore cannot change value by construction, not by
  coincidence — the same guarantee the existing two rules already give each other.
- When the factory call's receiver is a database context's own `Database` facade — recognised
  structurally, by the written shape, the same way every other rule in this resolver
  classifies a construct — the boundary is `context_connection`. Every other factory receiver
  reports `wrapper_connection`, unchanged from what a Field-Held Connection already produces.
- `context_connection` carries no resolved database of its own. It states which lookup applies
  — Context Connection Registration, keyed by the call site's declared receiver type — not a
  connection the wrapper holds. Resolving the actual database from that statement is later
  work; this ticket's whole acceptance is that the boundary is non-empty and honestly labelled.
- The value is recorded in the behaviour signature, exactly like the other two values. Nothing
  branches on it today, so the cost of a third value is the value itself — visible in every
  Contract Fingerprint that carries it, and nowhere else.

## Alternatives considered

**Reuse `wrapper_connection` for the factory receiver, whatever its shape.** Simpler — no new
vocabulary, no new field to plumb through `CommandSource` and `WrapperDefinition`. Rejected: it
would assert a single owned connection for a base class five Systems share, which is false on
its face and indistinguishable in the recorded fact from a wrapper that genuinely does hold one
connection (a Field-Held Connection). A later reader of the behaviour signature — or a future
rule that does branch on this value — would have no way to tell "the wrapper's own connection"
from "ask Context Connection Registration," because the fact was never recorded.

**Resolve the actual database now, inline in this ticket.** Rejected as premature and out of
this ticket's own scope: `SQLDbContext` has no single answer to resolve — the database follows
the *call site's* declared context type, a lookup this ticket does not perform. Recording
`context_connection` states the fact this ticket can prove (which lookup applies) without
guessing the one thing it cannot yet prove (which database that lookup returns).

## Consequences

- All three classified `SQLDbContext` methods report `context_connection` instead of an empty
  boundary. Combined with tickets 01, 02 and 04, the behaviour surface no longer fails on
  `connection_behavior_boundary_missing` — though `usp_ExecCmdGetCountAsync`, EF Core's raw-SQL
  execution shape, still blocks completeness on its own, unrelated reason until ticket 08.
- A Contract sharing `context_connection` across five Systems' derived context types is honest
  about what it does not yet know, rather than silently wrong about what it claims to know.
- The existing `SQLFunc` and `SQLObject` Contracts are unaffected: neither contains a single
  `CreateCommand` call, so the new rule is never reached for either, and their Contract
  Fingerprints — `context_connection` included — are unchanged byte for byte.
- The trade-off is hard to reverse in one direction only: once `context_connection` values
  exist in committed Contract Fingerprints, collapsing them back into `wrapper_connection`
  would silently claim ownership of a connection no wrapper holds. Adding a fourth boundary
  value later, should one become necessary, costs nothing this decision forecloses.
