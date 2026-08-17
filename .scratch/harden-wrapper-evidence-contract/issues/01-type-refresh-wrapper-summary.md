# 01 — Type `/refresh`'s wrapper_summary with a Pydantic model

**What to build:** `RefreshResponse.wrapper_summary` (currently an untyped `Dict[str, Any]`) becomes a validated Pydantic model matching exactly the field set `reconcile_refresh_wrappers`/`wrapper_observation_fields` already produce today. This is additive validation only — no field is renamed, dropped, or reshaped, and no currently-correct `/refresh` response should be rejected by the new model.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `RefreshResponse.wrapper_summary` is a typed Pydantic model, not `Dict[str, Any]`
- [ ] `review_items[].evidence_status` is restricted to the four known values: `proven`, `likely`, `unresolved`, `not_applicable`
- [ ] The model represents the existing aggregate fields (`evidence_statuses`, `totals`, and any other current `wrapper_summary` keys)
- [ ] A test asserts the model accepts the exact shape currently produced by a real `/refresh` run — this is a regression guard, not new behavior
- [ ] No field is renamed, dropped, or reshaped as part of this ticket
