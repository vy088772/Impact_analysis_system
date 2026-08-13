# 06 — Decompiler-sourced provenance marker end-to-end

**What to build:** Every contract produced from a decompiled snapshot (ticket 05) carries a distinct provenance marker (e.g. `evidence_kind: "decompiled_auto"`), separate from `contract_lifecycle_status`, that survives from the registry entry through to the refresh response's wrapper summary — so an auditor can find every contract that went active without a human ever reading the code, without a second lookup. `CONTEXT.md` gains a short clarification distinguishing `contract_lifecycle_status` (reused/created/preflight_failed/conflicted/selected/not_required) from this decompile-provenance marker, since the former is used extensively but not yet defined in the glossary.

**Blocked by:** 05.

**Status:** ready-for-agent

- [ ] `versioned_contract_from_proposal()` preserves an incoming `evidence_kind` (e.g. `decompiled_auto`) onto the registry entry instead of dropping it
- [ ] A registry entry created from a decompiled snapshot is queryable/distinguishable by this marker from one created via local-source onboarding or explicit selection
- [ ] `RefreshResponse`'s wrapper summary includes the provenance marker for each affected wrapper, requiring no `RefreshResponse` schema/type change (it's already an untyped dict)
- [ ] A contract produced via local-source onboarding or explicit selector never carries the `decompiled_auto` marker
- [ ] `CONTEXT.md` documents `contract_lifecycle_status` and clarifies it as distinct from the decompile-provenance marker
- [ ] Tests assert the marker's presence end-to-end: registry entry → preflight result → wrapper summary, using the existing `test_refresh_contract_preflight.py` seam
