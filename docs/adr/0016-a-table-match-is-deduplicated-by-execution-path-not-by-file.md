# A Table Match Is Deduplicated by Execution Path, Not by File

**Status:** Accepted
**Date:** 2026-09-04

## Context

`_prefer_table_match()` in `service/analyze_service.py` collects the access records that
`/find_by_table` returns. It keys them by file, and it keeps one record per file — the one that
`_table_match_rank()` scores highest. A write outranks a read, a direct access outranks an
indirect one, and a stored-procedure path outranks an inline one.

One program therefore reports one fact about one table, whatever paths reached it. A program
that reads `Quotation` through one stored procedure and writes it through another reports only
the write. A program that writes the same table through two different stored procedures reports
one of them, and the response does not say which of the two, or that there were two.

The consumer's glossary asks for the opposite. `llamaindex-spec-rag`'s **Writer Evidence
Identity** is defined as the deduplication identity that "preserves path and mutation
differences even when findings belong to the same program", and its **Path-scoped Writer
Evidence** states that "program-level access labels alone are insufficient". The docstring of
its `find_programs_by_table_with_access()` describes the same behaviour — 「同一支程式可能有多筆
命中；那是不同的事實，不會被合併」— and a live probe returns exactly one access type per program.
The documented behaviour does not exist, because this function removed it one layer down.

The collapse also blocks [ADR-0015](0015-an-unproven-execution-path-is-reported-not-dropped.md).
Under that decision a program can hold a proven read and an unproven write against the same
table. `_table_match_rank()` scores the write higher, so the unproven write wins the file's one
seat; a caller then filtering for proven writes discards it, and the proven read is already
gone. Repairing one loss would open another.

## Decision

`/find_by_table` deduplicates an access record by the identity of the Execution Path that
produced it — program, file, `path_id`, entry method, stored-procedure chain, and access type —
not by file.

Two records that agree on all of those are one fact, and collapse to one record. Two records
that differ in any of them are two facts, and both survive.

This is not the removal of deduplication. It is the replacement of a key that discards facts
with a key that discards repetition.

## Consequences

- A `/find_by_table` response grows. Its upper bound is the number of distinct Execution Path
  identities that reach the table, not the number of files. The PUR graph holds 962 DML
  operations touching `Quotation` across 310 stored procedures, so the growth must be measured
  rather than assumed.
- `_table_match_rank()` no longer decides which fact survives. It may still order the response.
- ADR-0015's proven read and unproven write both reach the caller. Neither displaces the other.
- The consumer's `Writer Evidence Identity` and `Path-scoped Writer Evidence` become true of
  the data, not just of the documentation.
- Response size becomes a presentation problem rather than a correctness one. The consumer
  already owns terms for that — **Inventory Projection** and **Inventory Completeness
  Metadata** — and this repository does not summarise on its behalf.

## Alternatives considered

**Keep the per-file key, add an evidence axis to the rank.** Scoring `proven` above `write`
would stop an unproven write displacing a proven read, and it is a two-line change. It still
answers the question "which single fact survives", so a caller still sees at most one of the
several true facts. It solves ADR-0015's interaction and leaves the glossary contradiction
untouched.

**Remove deduplication entirely.** Every path becomes a record. The bound is then the raw path
count, which for `Quotation` is the 962 operations crossed with the C# invocations that reach
them — one to two orders of magnitude above today, and directly against
`llamaindex-spec-rag`'s Answer Latency target of a ninetieth percentile under thirty seconds.
Identical repeated paths carry no information, so paying for them buys nothing.
