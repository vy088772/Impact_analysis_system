# Decide Contract Reuse by Fingerprint, Not Receiver Name, in Decompile-Based Onboarding

**Status:** Accepted
**Date:** 2026-08-14
**Amends:** ADR 0005

## Context

ADR 0005 lets refresh-time Contract Onboarding decompile a referenced external wrapper DLL. That decision has one guarantee: a complete result needs no human review step.

An implementation commit added `_active_contract_receivers()`. This function read the whole contract registry. It skipped decompilation for a receiver type whenever any contract used that type name, even from a different source system. This check ran before Contract Fingerprint comparison.

Contract Fingerprint is this system's only notion of contract identity. The `unified-database-invocation-classification` spec defines a Contract Fingerprint's source signature as independent of receiver names, assembly provenance, and discovery order. A receiver-type name plays no part in this identity.

The registry-wide skip broke this separation. One system's contract could block a different system's onboarding attempt for the same receiver-type name. This happened even when the two contracts had different Contract Fingerprints. The skip returned a false `unresolved` result instead of a correct new contract. It defeated ADR 0005's no-review guarantee.

No ticket specified this skip. ADR 0004, ADR 0005, and every ticket under `.scratch/automatic-external-wrapper-decompilation/issues/` are silent on any receiver-name-based check. The function was an unreviewed addition, not a decision.

## Decision

Remove `_active_contract_receivers()`. Remove its parameter and skip branch from `_populate_decompilation_proposals()`. Remove its call-site argument from `refresh_source()`.

Decompile-based Contract Onboarding no longer skips a receiver for a registry-wide, name-based reason. `contract_preflight.py` alone decides reuse versus create, by Contract Fingerprint comparison. Two systems can reference a receiver of the same type name. Preflight reuses one existing contract only when both fingerprints match. A fingerprint mismatch creates a new, separate contract.

Add no human-review gate for this new-contract case. Contract Fingerprint, not receiver-type name, is this system's sole notion of contract identity. A same-named, different-fingerprint contract is the exact case Contract Fingerprint exists to resolve automatically. A review gate here would restore the removed skip in a new form.

Keep the existing fingerprint-suffix naming convention for name collisions. A colliding name becomes `<name>-<fingerprint-prefix>`. Do not switch to a system-scoped convention, such as `<name>__<system_id>`. A system-scoped name would encode discovery order, or an origin system, into contract identity. That would contradict the Contract Fingerprint definition itself.

## Consequences

Decompile-based Contract Onboarding now runs for every unresolved external wrapper receiver with a traceable `.csproj` reference, unless the current refresh's own scan roots already hold source-backed evidence for that receiver. No registry-wide, cross-system receiver-type-name exception remains. Two systems can each auto-onboard a contract for a same-named receiver. Neither system's registry entry blocks the other.

A same-named, different-fingerprint contract can now reach `created` status with no human review. This restores the auto-onboarding guarantee from ADR 0005. The completeness bar from ADR 0004 and ADR 0005 stays the real safeguard: only a Verified Implementation Snapshot can reach this outcome.

Tests must cover the new behavior. A name-colliding, fingerprint-mismatched registry contract must not block a decompilation attempt. It must yield a fingerprint-suffixed created contract instead. The `active_contract_evidence` skip reason no longer appears in `wrapper_summary["decompilation"]`'s vocabulary.
