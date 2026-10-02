# A Request That Names Its Files Rates Them Without Retention

**Status:** Accepted
**Date:** 2026-10-02

## Context

[ADR-0013](0013-derived-execution-evidence-computed-once-per-scope.md) decides that the service derives Derived Execution Evidence once per scope. Every request of that scope filters the one result. [ADR-0017](0017-derived-execution-evidence-is-also-retained-on-disk.md) keeps a copy of that result on disk.

Some endpoints ask about one program, not about the whole scope. `/path_evidence` with program names is one of them. `/analyze` is another. These endpoints know the C# files that they need before they ask. A full derivation of a cold scope rates every file of the scan. For a large system, that work takes much more time than the rating of one program. An analyst who asks about one program on a cold scope would then wait longer than before.

The work of the spec "One Module Answers the Derived Execution Evidence for a Scope" moves these endpoints onto the Derived Execution Evidence module. This record states how that module answers a request that names its files.

## Decision

A request can give the module a list of needed files. The list changes only what the module does on a miss:

- A miss with no needed files derives the whole scope. The module retains the result in memory and on disk, as ADR-0013 and ADR-0017 decide.
- A miss with needed files rates those files only. The module does not retain this partial result, in memory or on disk.
- A hit serves the retained evidence of the whole scope, with or without needed files. The endpoint filters it.

The freshness rule does not change. The module takes the same five-input validity stamp and compares it by the same rule. A retained result with a stamp that does not match is never served. `refresh` skips the memory copy and the disk copy for every request.

A partial result equals the filtered whole result for three reasons:

- The rating of one file does not read the rating of another file.
- The Observed Call Evidence index always comes from the whole scan, also for a partial rating.
- A path_id depends only on its own Database Invocation and the graph.

## Consequences

- Only the miss of a request with needed files differs from ADR-0013. This is not a relaxation of the freshness check. A partial result is always a fresh derivation.
- A request with needed files on a cold scope stays as fast as before. The same request after a full derivation of the scope gets the retained evidence.
- Only full derivations enter the retention. So the number of retained scopes does not grow, and the present retention bound still holds.
- Two requests with needed files on one cold scope rate their files two times. This cost is accepted. A full derivation of a cold scope for each such request would cost more.
- A partial result never reaches the disk. So a later request never reads a partial result as the evidence of the whole scope.

## Alternatives considered

**A full derivation on every miss.** This obeys ADR-0013 with no exception. But the first program question on a cold scope would wait for the rating of every file. That is slower than today.

**Retain the partial result too.** The retention would then hold results that do not cover the scope. A later request for the whole scope would need a second rule to tell a partial entry from a full entry. The retention would also hold more entries per scope.
