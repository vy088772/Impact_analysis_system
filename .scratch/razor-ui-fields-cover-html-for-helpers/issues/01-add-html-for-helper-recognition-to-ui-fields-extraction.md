# 01 — Add `@Html.*For` helper recognition to `ui_fields` extraction

**What to build:** Extend `_extract_ui_fields` to recognize `@Html.<Method>For(<lambda>, ...)`
calls beside the existing `<th>`/`<label>`/`asp-for` handling. Classify each
recognized call by its Helper method: `DisplayNameFor` and `LabelFor` produce a
`label` entry; `DisplayFor` produces a `value` entry; `TextBoxFor` and
`TextAreaFor` produce an `input` entry; `HiddenFor` produces no entry at all.

For each recognized call, read the lambda's bound property. A direct
`m.Property` or `Model.Property` shape sets `data_field: "Property"` on the
entry, so `razor_display_field_resolver` resolves it against the view's
`@model` class exactly as it already does for `asp-for` labels — no change to
that resolver. A binding through a collection index (`m.Items[i].Property`) or
through a lambda parameter other than `m`/`Model` (a `foreach` loop variable,
for example) names a property on some other type. Keep these as an entry with
the raw bound expression as `text` and no `data_field`, so the resolver never
runs on them.

Leave `_extract_html_helpers` and its `RazorHelper`/`HtmlHelpers:` count
untouched — that pass serves a different purpose. Apply this uniformly to
every scanned system's Razor views; add no per-system configuration.

Increment the scan-cache version convention, since `ui_fields` contents change
shape for any Razor view using these Helpers.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `DisplayNameFor` with a direct `m.Property` binding produces a `label` entry with `data_field: "Property"`.
- [x] `LabelFor` with a direct `m.Property` binding produces a `label` entry with `data_field: "Property"`.
- [x] `DisplayFor` with a direct `m.Property` binding produces a `value` entry with `data_field: "Property"`.
- [x] `TextBoxFor` with a direct `m.Property` binding produces an `input` entry with `data_field: "Property"`.
- [x] `TextAreaFor` with a direct `m.Property` binding produces an `input` entry with `data_field: "Property"`.
- [x] `HiddenFor` produces no `ui_fields` entry.
- [x] A collection-indexed binding (`m.Items[i].Property`) produces an entry with the raw expression as `text` and no `data_field`.
- [x] A non-model lambda-parameter binding (a `foreach` loop variable, not `m`/`Model`) produces the same shape: raw text, no `data_field`.
- [x] The existing `<th>`/`<label>` (with and without `asp-for`) tests in `test_razor_parser_ui_fields.py` keep passing unchanged.
- [x] No change to `razor_display_field_resolver`.
- [x] The scan-cache version number is incremented.

**Note:** Recognition lives in `RazorParser._extract_ui_fields`
(`code_analyzer/razor_parser.py`) via a new `HTML_FOR_HELPER_PATTERN`. The
"direct binding" check is textual, not name-of-declared-lambda-parameter: it
matches the *identifier actually prefixing the property access* against
`m`/`Model` exactly. This was necessary because real IQCS markup uses
`@Html.DisplayFor(modelItem => item.UserName)` — a scaffolded lambda
parameter (`modelItem`) that is never referenced in the body, which instead
closes over an outer `foreach` variable (`item`). Checking the declared
parameter name would have wrongly treated this as safe; checking the
expression's own leading identifier correctly excludes it. Verified against
real usage in `data/repos/System_Dept_1/IQCS/Views` (93 files use
`DisplayNameFor`) before finalizing the regex, including collection-indexed
(`m.Items[0].Property`, `model.DataList[i].Model`) and nested (`Model.addcond
.ReceiveList`, two levels deep) shapes — both correctly fall through to raw
text with no `data_field`.

Ran the full test suite (`1038 passed, 11 failed`); the 11 failures are
pre-existing and reproduce identically on the unmodified baseline (verified
via `git stash`) — they need a live SQL Server / ODBC driver connection this
environment doesn't have, unrelated to this change. `tests/test_search_roles
.py` and `tests/test_sp_tables.py` fail to collect for the same reason.

Ticket 02 (spot-check STC and Y-DOCs/TTPUR scan caches) is separate and not
started.
