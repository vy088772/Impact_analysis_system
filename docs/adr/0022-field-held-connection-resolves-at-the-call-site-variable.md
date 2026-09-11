# Field-Held Connection Resolves at the Call-Site Variable

**Status:** Accepted
**Date:** 2026-09-11

## Context

Ticket 09 added a second connection lookup shape beside Context Connection Registration: a
class reads a named connection string into one of its own fields in the constructor, and a
raw ADO.NET call later opens a connection from that field. The measured `ETR` repository
is written entirely this way — thirty-five `new SqlConnection(...)` call sites, all reading
from a field assigned once, in the constructor.

A Database Invocation does not record the field. It records the variable at the call site —
often a local the field was copied into, not the field's own name. That leaves a real
alternative for where the Resolved Connection Source, and any reason it failed to resolve,
should attach: the field that was assigned, or the call-site variable the invocation actually
names.

Attaching only to the field would be invisible to the reader who has the invocation: nothing
in a `DbInvocation` names the field, so a reason recorded solely against it can never be
found by following the invocation back to its evidence.

That choice has a consequence of its own. The tracker resolves a connection by variable name
across one file, not by field or by method. Two unrelated methods that each happen to declare
a local named `con` share the same tracker entry. An early implementation treated a resolved
name as settled once any call site resolved it, and skipped recording a reason for a later
call site with the same name — which silently produced an empty result for a call site that
had never actually resolved, exactly the outcome ticket 09 forbids.

## Decision

The Resolved Connection Source, and any failure reason, attaches to the call-site variable —
the name the `DbInvocation` itself records — not to the field it was read from. The field
still carries its own record of why it failed to trace, but every call site inherits that
reason independently.

One call site resolving a variable name never settles another call site that shares the same
name. The tracker records a reason at every call site it visits, never skipping one because
an earlier one with the same name already resolved. When a field name is genuinely ambiguous
within one file, the reason a call site inherits comes from the nearest assignment by line,
not the first one in the file.

## Consequences

- A reader following a `DbInvocation`'s connection reason always finds it attached to the
  name the invocation itself carries, never a field name the invocation never mentions.
- Two methods sharing a local variable name (e.g. `con`) never contaminate each other's
  result — each call site's resolution, or reason for failing to resolve, is recorded on its
  own, even when the name has already resolved elsewhere in the same file.
- This is the same family of gotcha ADR-0018 (Project Connection Scope) guards against: a
  name is unique only within the scope that actually declares it, and merging two scopes
  under one shared name produces a confident wrong answer instead of a visible unresolved one.
