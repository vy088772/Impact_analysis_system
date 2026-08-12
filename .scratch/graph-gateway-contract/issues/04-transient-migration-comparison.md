# 04 — Transient Migration Comparison

**What to build:** Maintainers can review deterministic legacy-versus-Gateway differences without legacy records becoming a second cache, graph, or runtime relationship source.

**Blocked by:** 01 — Graph-Only Cache Contract; 03 — Evidence-Preserving Gateway Responses.

**Status:** ready-for-agent

- [x] The comparison report exposes deterministic `dropped`, `new`, `confidence_changed`, and `unresolved` categories with caller/source, evidence, reason, and source-kind context.
- [x] Comparison output can be rendered or saved as a review artifact but is never persisted as formal SQL relationships or used by graph, path, lookup, or flow consumers.
- [x] Representative fixtures demonstrate confirmed Gateway parity or explicit unresolved reasons, and prevent false `proven` detections for inline SQL and ordinary methods.
