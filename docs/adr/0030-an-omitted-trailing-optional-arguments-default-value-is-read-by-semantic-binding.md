# An Omitted Trailing Optional Argument's Default Value Is Read by Semantic Binding

**Status:** Accepted
**Date:** 2026-09-17
**Amends:** ADR 0028

## Context

ADR 0028 recorded one guarantee: the analyzer host records Observed Argument
Facts from the syntax alone, reads no Contract, and gains no Contract input
channel. `accepted-contract-resolves-its-calls`'s own Implementation
Decisions section said the same thing in the same words.

That phrasing overstated the mechanism. The shipped code also performs
semantic binding — the same binding the analyzer host already uses elsewhere
for a wrapper call's own method identity — to read an omitted trailing
optional argument's declared default value. A call site that omits a
trailing optional argument carries no syntax for that argument at all; the
default value exists only in the referenced assembly's own metadata, and
reading it needs semantic binding, not syntax.

This was a correct, load-bearing, tightly-guarded addition, not a defect. A
reader of ADR 0028 or the spec today would not learn it happened.

## Decision

The "from the syntax alone" guarantee is narrowed, not withdrawn. The
analyzer host reads an omitted trailing optional argument's declared default
value via semantic binding to the referenced assembly's own metadata, guarded
so that only a uniquely bound symbol — no candidate ambiguity — is trusted.
An unresolved or ambiguous binding leaves the argument's position unrecorded;
no guess is recorded in its place.

Semantic binding to a referenced assembly's own metadata is not a Contract
read. ADR 0028's "no Contract input channel" guarantee stands exactly as
recorded: the analyzer host still reads no Contract, and still gains no
Contract input channel, for this or any other purpose.

## Consequences

`accepted-contract-resolves-its-calls`'s own Implementation Decisions section
is corrected to point here for the full guard description, instead of
repeating the "from the syntax alone" phrasing without qualification.

No code changes accompany this amendment. The shipped code already contains
the refinement described here; only the written record catches up to it.
