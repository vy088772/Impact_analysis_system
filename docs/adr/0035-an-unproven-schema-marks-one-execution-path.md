# An Unproven Schema Marks One Execution Path; It Does Not Multiply It

**Status:** Accepted
**Date:** 2026-09-29

## Context

A table reference in a stored procedure can state no schema. The SQL Execution Graph then holds a target with an empty schema. T-SQL resolves that name through the default schema of the connecting identity, and the analysis cannot know that identity. The schema of the target is therefore unproven.

An architecture review of the canonical-object-identity spec (`.scratch/canonical-object-identity/spec.md`) found one producer step, as its finding B2. A target with an empty schema produced one Execution Path for each candidate schema that holds a table with that bare name. The candidate paths shared one `path_id`. The [ADR-0016](0016-a-table-match-is-deduplicated-by-execution-path-not-by-file.md) deduplication then kept one of them, and the consumers never received the others.

Story 7 of that spec once read [ADR-0015](0015-an-unproven-execution-path-is-reported-not-dropped.md) and ADR-0016 as a demand for one path per candidate schema. Neither decision demands it. ADR-0015 demands that an unproven path stays in the answer with its caveat. ADR-0016 demands that two different facts stay two records. One unknown schema is one fact with a caveat, not several facts.

## Decision

One target with an empty schema produces one Execution Path. An unproven schema marks that path's table match. It never multiplies the path.

- The table match falls back to the bare key when a target states no schema. The match record then carries `unproven_schema` in its `risk_flags`.
- The mark sits on the match record of that one path, not on the path itself. One path serves every table question in its scope, and a match on another target of the same path carries no mark.
- The Evidence Status stays `proven` when only the schema is unproven. A `likely` downgrade would change a path decision in two downstream readers.
- The `path_id` formula does not change. The Path Identity value holds no candidate schema field.

The reasons:

- One path per candidate schema turns one unknown fact into several facts, and at most one of them is true.
- One path holds many targets. One path per candidate schema of each target multiplies into a cartesian product of the candidate schemas.
- Three sites read `path_id` as the identity of one path: the ADR-0016 deduplication, the merge in `llamaindex-spec-rag`, and `/path_evidence`. Any path that shares a `path_id` with another path is lost at one of these sites.

## Rejected alternatives

**Put the candidate schema inside the `path_id` identity.** Each candidate path then gets its own `path_id`, and no site merges them. The change alters every `path_id` that exists, including the `path_id` of every path that has no unproven schema. It also keeps the several facts of which at most one is true.

**Add a table part to the ADR-0016 deduplication key.** The deduplication then keeps each candidate path. The merge in `llamaindex-spec-rag` and `/path_evidence` still read the `path_id`, so they still read two paths as one. The loss moves from one site to two others.

## Consequences

- An analyst sees one path for one route, with an `unproven_schema` mark when the table match relied on a bare name.
- A path whose schema is proven carries no mark. The mark describes the target, never the question.
- The producer and the two sites in `llamaindex-spec-rag` that key on the whole stored-procedure chain count the same facts. No producer step merges two schemas.
- A field that joins the Path Identity value later changes every `path_id`. That change needs its own ADR.
- ADR-0015 and ADR-0016 gain no amendment note. Neither decision changes.

## Amendment (2026-09-30): the mark stays for three cases only

[ADR-0037](0037-an-unstated-schema-resolves-as-sql-server-resolves-it.md) adds Schema Resolution. The graph builder now resolves a target that states no schema, when the listing decides. A resolved schema is proven and carries no mark. The Context section above describes the state before that change.

The Unproven Schema mark stays for three cases:

1. The listing does not hold the name. A temp table, a table variable, and an object of another Database are examples.
2. The reference is `db..name`, and that Database has no local cache.
3. Neither the module's schema nor `dbo` holds the name.

The Decision section stays valid for these cases. One target with an empty schema produces one Execution Path. The mark never multiplies that path.

The rule for a procedure call now agrees with the rule for a table target. An unqualified call links to the one procedure that Schema Resolution names. It no longer links to every listed procedure with that bare name.

A call that no listed procedure answers gives one Execution Path with the reason `called_procedure_not_in_graph`. That path carries `unproven_schema` in its own `risk_flags` when the schema source of the call is `unresolved`. This narrows the second bullet of the Decision section, which keeps the mark off the path. That bullet still holds for a table target. The path of such a call holds one target, the call, and it gives no table match record. So the mark of a call sits on the path, and it reaches no other target. A call that resolves to `sys` has a proven schema and carries no mark.
