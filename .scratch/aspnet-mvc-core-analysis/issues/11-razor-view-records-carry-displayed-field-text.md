# 11 — Razor view records carry displayed field text

**What to build:** An analyst can ask which fields a Core screen displays, and gets the text a user
would actually see.

The Razor parser produces the same structured record shape the WebForms parser
produces, so the view-layer summary, the flow chain builder and the snippet
extractor consume both without branching.

Field text comes from three sources, because the measured repositories use three
different conventions. One of them writes no readable label in the view at all:
its labels resolve through a display attribute on a model property to an entry
in a resource file.

**Blocked by:** 04.

**Status:** resolved

- [x] Plain markup text in table headers and labels is extracted as displayed field text.
- [x] A model-bound attribute contributes the model property it names.
- [x] A display attribute carrying a literal label contributes that label with no resource lookup.
- [x] A display attribute naming a resource entry contributes the entry's text.
- [x] A display attribute whose resource entry is missing contributes nothing and says why, rather than contributing the key.
- [x] The Razor view record shape matches the WebForms view record shape, and the view-layer summary renders both without special-casing.
- [x] The scan cache version increments, because stored view records change shape.
- [x] A view from each of the three measured conventions yields its displayed field text.

## Comments

Implemented via TDD (red→green per slice), then a two-axis (Standards + Spec)
code review, both clean after two follow-up fixes applied from the findings.

**`code_analyzer/razor_parser.py`**: `RazorParser` now populates `ui_fields`
(same key vocabulary as `ASPXParser`'s — `kind`/`text`/`data_field`), from two
markup-only sources: `<th>` text (`kind="header"`) and `<label>` text/`asp-for`
(`kind="label"`). A `<label asp-for="X">` with no inner text — the Core
convention where `LabelTagHelper` generates the label at runtime from the
model property's own `[Display]` attribute — still contributes `data_field: X`
so the property is never silently dropped; a later pass resolves the actual
text.

**`code_analyzer/csharp_parser.py`**: `PropertyInfo` gained
`display_literal_label`/`display_resource_type`/`display_resource_key`
(`code_analyzer/models.py`). `_extract_properties` looks back from each
property declaration for an immediately preceding `[Display(...)]` attribute
(tolerating other attributes in between, stopping at the first non-attribute
content so an earlier property's own `[Display]` is never misattributed to a
later one). `ResourceType = typeof(...)` selects the resource-file branch;
plain `Name = "..."` alone is the literal-label branch. Returns a
`_DisplayAttribute` `NamedTuple`, not a positional tuple (code-review Standards
finding).

**`code_analyzer/resource_file_resolver.py`** (new): `resolve_resource_entry`
looks up one `.resx` key by the resource type's simple class name, searched
under the project root. Returns `(text, reason)` — a missing file, an
unreadable file, a missing key, and an empty value each get their own
`reason` string; the raw key is never handed back as a fallback "label".

**`code_analyzer/razor_display_field_resolver.py`** (new): pure
`resolve_razor_display_fields(razor_results, csharp_results, project_root)`
mutates each Razor `ui_fields` entry in place — matches a view's `@model` type
to a parsed C# class (preferring a namespace-qualified match over a bare class
name, so two same-named model classes in different namespaces never cross-bind
— a gap the Spec review caught), looks up the named property, and resolves
`text` from `display_literal_label` or, failing that, via
`resolve_resource_entry`. A property name an `asp-for` names but that doesn't
exist on the resolved model class now also gets its own
`unresolved_reason` (`model_property_not_found:...`) instead of silently
staying unexplained — the second Spec-review finding.

Wired into `ProjectScanner.scan_project`/`refresh_csharp_files`/
`refresh_view_files` (all three, since either a C# or a Razor file changing can
affect resolution). `service/scan_store._CACHE_VERSION` bumped to 33.

`service/analyze_service._view_layer_summary` needed **no change** — it already
reads `ui_fields` via `getattr` with no framework branch, so Razor's fields
render through it automatically once populated.

Tests (all new, 25 total): `tests/test_razor_parser_ui_fields.py`,
`tests/test_csharp_parser_display_attribute.py`,
`tests/test_resource_file_resolver.py`,
`tests/test_razor_display_field_resolver.py`,
`tests/test_razor_view_layer_fields_end_to_end.py` (the last drives the real
parsers + resolver + `_view_layer_summary` together, covering all three
measured conventions in one pass, plus the missing-resource-never-falls-back-
to-the-key case).

Full suite: 784 passed / 11 failed (same 11 pre-existing baseline names as
before this ticket, confirmed unchanged) / 5 skipped.

