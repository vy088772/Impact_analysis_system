# Stage Refresh-Time Contract Onboarding Before Formal Classification

**Status:** Accepted
**Date:** 2026-08-10

## Context

`wrapper_contract` selects reusable semantics for an unavailable external wrapper, but a system may have no selector or may retain a stale selector after a library change. The desired operator workflow is one `refresh_cli` operation that pulls source, discovers enough source/DLL evidence to establish contracts, classifies the current source, reconciles wrapper observations, and reports `proven`, `likely`, and `unresolved` results.

The previous boundary required normal refresh to leave both the external contract registry and the system catalog untouched. That avoided accidental semantic changes, but it also forced a separate acceptance step for a contract that could already be established from complete source-backed evidence. Writing immediately during preflight would create the opposite risk: an incomplete or ambiguous observation could become active semantics before the source scan has validated the result.

## Decision

Use a staged refresh-time onboarding workflow:

1. Run one raw source analysis after `git pull`.
2. Normalize the catalog selector. Missing, null, blank, empty-array, and all-blank values are unspecified. A missing named contract makes a string selector unspecified; any missing member makes an array selector invalid as a whole.
3. If a valid selector exists, use its string or explicit contract set for formal classification and do not create or overwrite contracts automatically.
4. Otherwise, run Contract Preflight from local source or a verified implementation snapshot tied to an exact external assembly identity. Only complete receiver, method, mode, and sink semantics may produce a staged active contract. Incomplete, conflicting, ambiguous, reflection-only, or name-only evidence remains a review candidate.
5. Reuse equivalent existing receiver contracts. Serialize one complete contract as a string selector and multiple complete contracts as a deterministically sorted array. Array order has no precedence meaning.
6. Run formal Database Invocation classification and wrapper reconciliation against the staged registry/catalog view. Source-backed implementation evidence remains stronger than an external selector, and a selector never proves a procedure target or database identity.
7. Commit the registry and catalog selector only after formal classification and reconciliation succeed. Treat the two files as one logical transaction with validated temporary files, a transaction identity, replacement of both targets, and rollback/recovery if the second replacement or post-commit validation fails.

An invalid selector is preserved in diagnostics until a successful transaction replaces it. An incomplete preflight does not block unaffected direct or source-backed invocations; affected external wrappers remain `unresolved`. Program-scoped refresh cannot perform onboarding and requires an existing valid selector or a prior completed full-system onboarding refresh.

## Consequences

The normal refresh command becomes sufficient for safe contract onboarding and does not need a mandatory discovery or acceptance command for complete source/DLL-backed semantics. Raw analysis is performed once and the staged contract view is reused for formal classification.

The registry and catalog can now change as a consequence of a successful refresh, so tests and operational review must cover selector normalization, deterministic string/array serialization, staged proposal validation, and two-file rollback. Cross-repository file replacement is a logical transaction rather than a native filesystem transaction and therefore needs explicit recovery handling. Explicit acceptance remains available for incomplete review candidates and deliberate semantic edits.

**Amended by ADR 0005**: the "verified implementation snapshot" evidence source now also includes an automated decompilation of a referenced external assembly, under narrower additional conditions. See [0005-automatic-decompilation-for-external-wrapper-onboarding.md](./0005-automatic-decompilation-for-external-wrapper-onboarding.md).

**Completion note (2026-08-17)**: "one logical transaction" above was implemented as `commit_staged_contract_transaction` but only wired into refresh-time onboarding. The explicit acceptance workflow (`service/contract_acceptance.py`, `accept_external_wrapper_contract`) kept its own bespoke rollback-only write, so a crash mid-write during manual acceptance had no recovery record even though refresh-time commits did. `accept_external_wrapper_contract` now commits through the same `commit_staged_contract_transaction`, closing that gap. The two entry points remain independent in *when* they trigger (automatic detection vs. explicit human review); they now share one *how* for writing the two files.