# An Unproven Execution Path Is Reported, Not Dropped

**Status:** Accepted
**Date:** 2026-09-04

## Context

`filter_table_accesses()` in `service/graph_queries.py` decides which Execution Paths become
access records in a `/find_by_table` response. It applies one gate: the path's evidence must be
`proven`, and the path must not carry the `dynamic_sql` risk flag. A path that fails produces
no record at all — not a weaker record, not a record with a caveat. Nothing.

`_build_path()` in `service/execution_path_builder.py` decides the evidence value that gate
reads. It downgrades a whole path to `unresolved` when any of its relationship targets fails to
resolve to a node, and `missing_targets` joins the missing reads to the missing writes. One
unresolvable read therefore erases the proven write in the same DML operation.

The two rules together produced a measured, silent loss. `llamaindex-spec-rag`'s
[ticket 02](../../../llamaindex-spec-rag/.scratch/first-round-exact-lookup-misses/issues/02-the-reverse-lookup-returns-a-node-id-that-names-no-node.md)
found six reverse-lookup questions missing seven required programs, every one of them a program
whose stored procedure holds a literal `INSERT` or `UPDATE` against the table, and whose C#
call is a `proven` Database Invocation. In the PUR cache, 272 of 2,919 DML operations that
write a real table — 9.3 percent — carried at least one unresolvable target.

The defect that produced those unresolvable ids is repaired separately. This ADR is about what
happens next time, whatever the cause. Unresolved Dynamic SQL is a permanent cause: nine such
nodes exist in the PUR graph, and no repair will ever prove them.

The consumer treats this response as authoritative. `llamaindex-spec-rag`'s
[ADR-0009](../../../llamaindex-spec-rag/docs/adr/0009-exact-evidence-is-authoritative-and-semantic-evidence-is-replaceable.md)
makes exact evidence authoritative, and its
[ADR-0010](../../../llamaindex-spec-rag/docs/adr/0010-the-first-agent-round-fixes-the-analysis-scope.md)
freezes that evidence as the analysis scope after the first round. An authoritative response
that drops what it could not prove is read as a complete answer, and nothing downstream
questions it.

## Decision

An Execution Path whose evidence is not `proven` is reported, with its Evidence Status and its
`unresolved_reason`, rather than being removed from the response.

The gate moves from the producer to the consumer. `filter_table_accesses()` emits a record for
every path that reaches the named table, proven or not. A caller that wants proven facts asks
for proven facts, and the response tells it how many records that request excluded.

A record that is not `proven` claims no mutation. It states that a path reaches the table and
that the service could not prove what it does there. `/find_by_table(write_only=True)` keeps
its present meaning exactly: proven writes and nothing else.

This decision does not change what counts as proven. It changes only whether the unproven is
visible.

## Consequences

- A `/find_by_table` response with `write_only=False` grows. It now carries paths that were
  previously invisible, including every Unresolved Dynamic SQL path.
- `write_only=True` responses do not grow. They gain an excluded count.
- A caller can distinguish "no program does this" from "the service could not prove it". That
  distinction was not expressible before.
- `llamaindex-spec-rag` maps a non-proven record onto its own **Possible Writer** term and
  reports it as an Evidence Gap. It does not add it to its Locked Analysis Scope, so an
  unprovable path costs disclosure, not analysis budget. That mapping is its decision, not this
  repository's; see [ADR-0007](0007-evidence-status-name-collision-with-llamaindex-spec-rag.md)
  for why the two Evidence Status vocabularies must not be conflated.
- The evidence downgrade in `_build_path()` stays as it is. A path with one unresolvable target
  is still not proven. It is now still reported.
- Tests that assert the present drop behaviour must be rewritten. `tests/test_graph_queries.py`
  is the main one.

## Alternatives considered

**Keep dropping, and rely on the repair.** Repairing the unresolvable ids removes the large
majority of the loss. It does not remove Unresolved Dynamic SQL, and it does not protect
against the next cause. The loss was invisible for as long as it existed precisely because the
response could not express it, so a repair alone leaves the same blind spot in place.

**Downgrade per target instead of per path.** A path could keep its proven writes while marking
only its unresolvable targets. This is a larger change to `_build_path()` and to the meaning of
a path's evidence value, and it does not help Unresolved Dynamic SQL, where the whole operation
is unknown. It remains available later; this decision does not block it.
