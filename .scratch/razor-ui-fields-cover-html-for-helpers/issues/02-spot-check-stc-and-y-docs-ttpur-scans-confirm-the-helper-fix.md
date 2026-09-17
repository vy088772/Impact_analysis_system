# 02 — Spot-check STC and Y-DOCs/TTPUR scans confirm the helper fix

**What to build:** Re-scan or re-parse the Razor views of two systems other
than IQCS — STC (`data/scan_cache/fbe54427b2bf7db0.pkl`) and Y-DOCs/TTPUR
(`data/scan_cache/ee4df0cc3ec5f807.pkl`) — and confirm their `ui_fields` now
include entries produced by `DisplayNameFor`, `LabelFor`, `DisplayFor`,
`TextBoxFor`, and `TextAreaFor` wherever their views use these Helpers, with
`kind` and `data_field` matching what Ticket 01 defines. This confirms the fix
generalizes past IQCS without any per-system change, per the spec's
uniform-application requirement.

**Blocked by:** 01 — Add `@Html.*For` helper recognition to `ui_fields` extraction

**Status:** ready-for-agent

- [ ] STC's refreshed scan cache shows Helper-produced `ui_fields` entries with correct `kind` and `data_field` for at least one view using each observed Helper.
- [ ] Y-DOCs/TTPUR's refreshed scan cache shows the same.
- [ ] No system-specific code change was needed to get this result.
