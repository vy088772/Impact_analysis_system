# Derived Execution Evidence Is Also Retained on Disk, Not Only in Memory

**Status:** Accepted
**Date:** 2026-09-04

## Context

[ADR-0013](0013-derived-execution-evidence-computed-once-per-scope.md) decided that Derived
Execution Evidence is derived once per (repository scan, SQL Cache Identity) scope and reused by
every later request for that scope. That reuse holds only inside the process that derived the
evidence, and only for as long as the bounded in-memory retention (ticket 03/06) keeps the scope:
a service restart discards the retention entirely, and a shared service serving many analysts
evicts a scope once the retention bound is reached (`DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT`).
Both send the next request for that scope back through a full rebuild of a result that is still
correct — for one measured scope of 3,719 Execution Paths, a rebuild costs 63.59 seconds. The
analyst asking the first question after a restart, or after their scope has aged out of the
retention, pays that cost again even though nothing about the scope's inputs has changed.

## Decision

Derived Execution Evidence is written to disk, one file per scope, in addition to being held in
memory. The file is keyed only by the scope's own identity
(`DerivedExecutionEvidenceScope`: repository scan roots, Database identity, wrapper contract
selector) — never by the object a request asks about, which would multiply files per scope and
contradict ADR-0013's decision that one derivation serves every object asked within a scope. Disk
use follows the number of distinct scopes ever derived, not the number of times they are
refreshed: a scope nobody asks about again keeps its file, and no expiry rule is added.

The freshness rule ADR-0013 established, and ticket 05 sharpened to compare each input's own
recorded content rather than Python object identity, is not relaxed for the disk-backed copy. A
stored file is served only when its recorded validity stamp — the same five-input stamp
(repository scan, SQL Cache, external wrapper contract, contract registry, wrapper review
exclusions) the in-memory retention already compares — still matches a freshly taken reading. An
explicit refresh ignores the stored file entirely, the same way it already ignores the in-memory
entry.

An unreadable or truncated stored file is treated as a cache miss, never as an error: the request
derives instead, the same tolerant handling `scan_store` already applies to a damaged scan cache
file. The write itself is atomic — a temporary file is written and renamed onto the target on the
same filesystem — so a reader never observes a partly written file. No lock is taken around a
derivation: the service is concurrent, so two requests can derive one new scope's evidence at the
same time, and both are allowed to run and both are allowed to write, because a pure derivation
from the same inputs produces equal results regardless of which write lands last. A lock would
hold a request thread idle while another derivation ran, for a race whose two possible outcomes
are already interchangeable.

## Consequences

- A reverse lookup's cost after a restart, or after an eviction, now matches the cost of a
  back-to-back request in the same process for the same scope: a deserialize, not a rebuild.
  Only the very first request for a scope — one whose inputs have never been derived before, or
  whose inputs just changed — pays the full derivation cost.
- Disk use scales with the number of distinct scopes ever derived. This repository does not
  expire scope files; if that growth becomes a problem, expiring them is a new decision, not an
  implicit consequence of this one.
- The disk-backed copy carries no fallback weaker than the in-memory one: it is exactly as
  strict about freshness, and exactly as willing to be wrong-never (only slow) about it, as
  ADR-0013 requires. Relaxing that check for the disk copy specifically — for latency, for disk
  space, or for implementation convenience — would be as much a reversal of ADR-0013 as relaxing
  it for the in-memory copy, and needs its own decision record.
- This ADR does not restate the five tracked inputs or their comparison rule; both are decided in
  ADR-0013 and ticket 05, and are reused unchanged here.
