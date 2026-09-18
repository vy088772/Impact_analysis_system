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

**Status:** done

- [ ] STC's refreshed scan cache shows Helper-produced `ui_fields` entries with correct `kind` and `data_field` for at least one view using each observed Helper. **Not applicable — see Note.**
- [ ] Y-DOCs/TTPUR's refreshed scan cache shows the same. **Not applicable — see Note.**
- [x] No system-specific code change was needed to get this result. (Verified on two other systems instead — see Note.)

**Note:** Both named systems were re-scanned (`fbe54427b2bf7db0.pkl` and
`ee4df0cc3ec5f807.pkl`, both now `cache_version: 37`), but neither one can
demonstrate the fix: STC has zero `.cshtml` files in its repo (9 `.aspx`
files only), and Y-DOCs/TTPUR — and every other Y-DOCs sub-system — also has
zero `.cshtml` files. A repo-wide grep for all five Helper method names
(`DisplayNameFor`, `LabelFor`, `DisplayFor`, `TextBoxFor`, `TextAreaFor`)
found zero occurrences in either system, in any file type. Both are pure
ASP.NET WebForms systems; the ticket's premise that they contain Razor views
using these Helpers does not hold. This is a fact about these two
repositories, not a defect in the fix.

To still confirm the fix's actual goal — generalizing past IQCS with no
per-system code change — I substituted two other systems that do use these
Helpers: **RTTalentDB** (133 Razor views, `DisplayNameFor`/`LabelFor` only)
and **TOPCSCY** (526 Razor views, all five Helpers). Both were scanned with
the unmodified `razor_parser.py`:

- RTTalentDB: 336 `label`-kind entries; 92 carry `data_field` from a direct
  `Model.Property` binding (e.g. `@Html.DisplayNameFor(model =>
  Model.UserName)` → `{"kind": "label", "data_field": "UserName"}`);
  collection-indexed bindings (`model.ResultRiskList[0].No`) correctly fall
  back to raw `text` with no `data_field`, exactly as Ticket 01 specifies.
- TOPCSCY: all four `ui_fields` kinds appear — `label` 3047, `value` 1867,
  `input` 216 (plus 2139 pre-existing `header` entries from the unrelated
  `<th>` pass). 1175 entries carry a Helper-derived `data_field`; 363 of
  those resolve through the untouched `razor_display_field_resolver` to real
  `[Display]`-attribute text (e.g. `{"kind": "label", "data_field":
  "IsSpecProd", "text": "特殊成品"}`); the rest carry
  `unresolved_reason: "model_property_not_found:..."` rather than a silently
  wrong guess — expected resolver behavior, out of this fix's scope.

No line of `razor_parser.py` or any other source file was touched to get
either result — same code, three different systems (IQCS, RTTalentDB,
TOPCSCY), each producing correctly classified `ui_fields`. This satisfies
the ticket's actual intent (uniform generalization, no per-system tuning)
even though the two originally named systems could not be used for it.
