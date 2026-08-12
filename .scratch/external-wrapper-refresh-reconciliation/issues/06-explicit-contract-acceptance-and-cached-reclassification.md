# 06 — Explicit Contract Acceptance and Cached Reclassification

**What to build:** Provide a deliberate acceptance workflow for reviewed external-wrapper contract proposals. The workflow must validate and apply registry changes, optionally update the system selector, produce a reviewable diff, and reclassify cached raw invocation facts without rerunning the C# analyzer. Refresh-time preflight may independently stage complete source/DLL-backed semantics when no valid selector exists; existing contracts such as `sqlobject` must be reused rather than duplicated.

**Blocked by:** 05 — Review-Only External Contract Proposals

**Status:** ready-for-agent

- [x] A reviewed proposal can be explicitly accepted; ordinary refresh has only the conditional preflight path for complete evidence and never implicitly accepts incomplete proposals.
- [x] Acceptance validates receiver types, method identity, allowed `mode` values, sink values, contract uniqueness, and any requested system selector before writing active configuration.
- [x] Incomplete proposals with no approved semantic `mode` or `sink` are rejected and remain review-only.
- [x] Acceptance produces a reviewable registry/catalog diff and does not commit changes automatically.
- [x] The existing `sqlobject` contract is reused for `SQLObject` observations instead of creating a duplicate contract.
- [x] Changing only contract configuration reclassifies existing cached raw facts without invoking the C# analyzer or changing source snapshots.
- [x] A source revision still requires a normal full or program-scoped refresh before new raw observations can be classified.
- [x] Acceptance, validation, conditional atomic write, reuse, and no-rescan behavior are covered by focused tests.
