# 07 — Migrate refresh_cli to the evidence_status module

**What to build:** `refresh_cli.py` reads `wrapper_summary.review_items[].evidence_status` through the new `evidence_status` module instead of direct dict access — even though its current reads are already correct, so all three real call sites go through one seam and a future producer-side rename can't slip through at the one site left on the old pattern.

**Blocked by:** 04 (the module must exist), 05 (fixture rewrite needs the validation helper).

**Status:** ready-for-agent

- [ ] `refresh_cli.py` reads `wrapper_summary.review_items[].evidence_status` through the `evidence_status` module, not direct dict access
- [ ] `tests/test_refresh_cli.py` fixtures are rewritten using the schema-validation helper (ticket 05) instead of hand-written dicts
- [ ] Existing CLI output/behavior is unchanged
