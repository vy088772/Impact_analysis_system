# Razor `ui_fields` Cover `@Html.*For` Helper Bindings

Status: ready-for-agent

Found while comparing an IQCS scan cache against its source during a manual
review. Companion to
`.scratch/unresolved-connections-require-a-database-receiver-type/`, found
and root-caused in the same review; the two are unrelated in cause and are
tracked separately.

## Problem Statement

An analyst asking what a Razor view actually shows a user gets `ui_fields`
back empty, or nearly empty, for most of this codebase's views, because
extraction only recognizes a `<th>` and a `<label>` carrying `asp-for` —
and this codebase's MVC-style views overwhelmingly label and bind fields
through `@Html.DisplayNameFor()`, `@Html.DisplayFor()`,
`@Html.TextBoxFor()`, and `@Html.TextAreaFor()` instead.
`Views/IQCResultCfm/IQCResultCfmBatchPVView.cshtml`, one measured example,
uses these Helpers for every label and input on the screen and reports back
one stray leftover string from an unrelated loop body. The analyst is told
the screen shows almost nothing, which is false: the screen shows the same
kind of information every other screen shows, written in a markup shape the
parser never learned.

## Solution

`_extract_ui_fields` also recognizes `@Html.<Method>For(<lambda>, ...)`
calls, classified by which Helper method is used: `DisplayNameFor` and
`LabelFor` contribute a label entry, `DisplayFor` contributes a value entry,
`TextBoxFor` and `TextAreaFor` contribute an input entry. `HiddenFor`
contributes nothing — a hidden field is never something a user sees, and
`ui_fields` exists to answer what a screen displays.

Each recognized entry carries the bound property name as its `data_field`,
which the existing `razor_display_field_resolver` already resolves against
the view's `@model` class without any change on its side. That resolver
already turns any `ui_fields` entry carrying a `data_field` into real
display text through the model property's `[Display]` attribute — it was
built for exactly this shape of input and has been sitting unused for
MVC-style views since it shipped, because nothing upstream of it ever
produced a `data_field` from this markup shape.

Only a direct binding — `m.Property` or `Model.Property` — earns a
`data_field`. A binding through a collection index (`m.Items[i].Property`)
or through a lambda parameter that is not `m`/`Model` (a `foreach` loop
variable, for instance) names a property belonging to some other type, not
the view's own `@model` class. Resolving it against `@model` risks a silent
wrong match whenever that other type happens to share a property name with
the view's own model. These two shapes still produce an entry — kept as raw
bound-expression text — but no `data_field`, so they never reach the
resolver. This mirrors the choice the parser already makes when a `<label>`
carries a property name it cannot otherwise place.

## User Stories

1. As an analyst, I want a Razor MVC view's `ui_fields` to include every
   field it labels or lets a user edit through `DisplayNameFor`, `DisplayFor`,
   `TextBoxFor`, or `TextAreaFor`, so that the screen's actual content
   matches what the scan reports.
2. As an analyst, I want a label produced by `DisplayNameFor`/`LabelFor`
   classified distinctly from a value produced by `DisplayFor` and an input
   produced by `TextBoxFor`/`TextAreaFor`, so that I can tell a caption from
   an editable field without reading the view's markup myself.
3. As an analyst, I want a `HiddenFor` field left out of `ui_fields`, so that
   the report only ever names what a user can actually see.
4. As an analyst, I want each of these entries' displayed text resolved
   through the view's `@model` class's `[Display]` attribute wherever the
   binding is direct, so that I read the same caption a user would see, not
   the bare property name.
5. As an analyst, I want a binding through a collection index or a
   non-model loop variable to still appear in the report as raw text, so
   that a screen written this way is never quietly reported as having fewer
   fields than it does.
6. As an analyst, I want that same collection-index or loop-variable binding
   never resolved against the view's own `@model` class, so that I am never
   shown a caption that happens to belong to some unrelated property of some
   other type.
7. As a maintainer, I want the new Helper recognition to sit inside
   `_extract_ui_fields` beside the existing `<th>`/`<label>`/`asp-for`
   handling, so that `ui_fields` keeps one extraction entry point rather
   than gaining a second, parallel one.
8. As a maintainer, I want no change to `razor_display_field_resolver`, so
   that the existing Display-attribute resolution pipeline is reused exactly
   as it already works for `asp-for` labels today.
9. As a maintainer, I want this fix to apply uniformly to every scanned
   system's Razor views, so that a system other than IQCS gets the same
   coverage without any system-specific change.
10. As a reviewer, I want a test for each of `DisplayNameFor`, `LabelFor`,
    `DisplayFor`, `TextBoxFor`, `TextAreaFor` asserting its kind and
    `data_field` for a direct `m.Property` binding, so that every supported
    Helper is covered individually.
11. As a reviewer, I want a test asserting `HiddenFor` produces no
    `ui_fields` entry at all, so its exclusion is enforced rather than
    assumed.
12. As a reviewer, I want a test asserting a collection-indexed binding and
    a non-model lambda-parameter binding each produce an entry with no
    `data_field`, so that the unsafe-shape guard is under test rather than
    merely described.
13. As a reviewer, I want the existing `<th>`/`<label>`/`asp-for` tests in
    `test_razor_parser_ui_fields.py` to keep passing unchanged, so that the
    new Helper support is proven additive.

## Implementation Decisions

- `_extract_ui_fields` gains recognition of `@Html.<Method>For(<lambda>,
  ...)` calls, classified by `<Method>`: `DisplayNameFor`/`LabelFor` → kind
  `label`; `DisplayFor` → kind `value`; `TextBoxFor`/`TextAreaFor` → kind
  `input`; `HiddenFor` → no entry.
- A recognized call's `<lambda>` is read for its bound property. A direct
  `m.Property` or `Model.Property` shape contributes `data_field:
  "Property"`. A collection-indexed shape or a lambda parameter other than
  `m`/`Model` contributes an entry with no `data_field`, keeping only the
  raw bound expression as `text`.
- No change to `razor_display_field_resolver` — it already resolves any
  `ui_fields` entry carrying a `data_field` against the view's `@model`
  class, independent of which markup produced that entry.
- No change to the existing `_extract_html_helpers` counting pass or its
  `RazorHelper`/`HtmlHelpers:` count — that pass and this one serve
  different purposes and stay independent.
- Applies uniformly to every scanned system's Razor views; no per-system
  configuration.
- Scoped to the five Helper methods actually observed in this codebase
  (`DisplayNameFor`, `LabelFor`, `DisplayFor`, `TextBoxFor`, `TextAreaFor`)
  plus the excluded `HiddenFor`. A Helper not yet seen in any scanned system
  is added when one appears.
- The scan-cache version convention requires an increment, since `ui_fields`
  contents change shape for any Razor view using these Helpers.

## Testing Decisions

A good test here asserts what `ui_fields` contains for a given view's
markup, never which internal branch of the parser produced it.

**Seam.** `RazorParser().parse_file()` → `.ui_fields`, exactly the seam
`tests/test_razor_parser_ui_fields.py` already exercises, writing markup to
a `tmp_path` `.cshtml` fixture and asserting on the returned list.

- One test per Helper (`DisplayNameFor`, `LabelFor`, `DisplayFor`,
  `TextBoxFor`, `TextAreaFor`) with a direct `m.Property` binding, asserting
  `kind` and `data_field`.
- One test asserting `HiddenFor` produces no entry.
- One test asserting a collection-indexed binding (`m.Items[i].Property`)
  produces an entry with the raw expression as `text` and no `data_field`.
- One test asserting a non-model lambda-parameter binding (a `foreach`
  variable, not `m`/`Model`) produces the same shape of entry: raw text, no
  `data_field`.
- The existing tests in `test_razor_parser_ui_fields.py` (`<th>`, `<label>`
  with and without `asp-for`) continue to pass unchanged.

## Out of Scope

- Resolving a collection-indexed or non-model-lambda-parameter binding to
  actual display text. Deliberately left as raw text; a future spec could
  add collection-item-type resolution if this reporting gap turns out to
  matter in practice.
- Any change to `razor_display_field_resolver` itself.
- `.scratch/unresolved-connections-require-a-database-receiver-type/` —
  tracked separately; unrelated cause, unrelated code.
- `@Html`/`@Url`/`@Ajax` Helpers beyond the five named and the excluded
  `HiddenFor` — scoped to what this codebase's views actually use today.

## Further Notes

- Originating review: a manual comparison of an IQCS scan cache
  (`data/scan_cache/d817e29ab991764b.pkl`, source commit
  `b6c8e9d676f61aca0951a31240cdab0d2844f89f`) against its source. The same
  review surfaced the connection-candidate noise tracked in the companion
  spec and a suspected SP wrapper command-mode bug that a follow-up
  investigation found was not a bug (see that spec's Further Notes).
- Measured Helper usage across IQCS's `.cshtml` files at review time:
  `DisplayNameFor` 1173 occurrences, `DisplayFor` 345, `HiddenFor` 37,
  `TextBoxFor` 29, `TextAreaFor` 3. Only `System_Dept_1` was cloned locally
  at review time, so usage in other departments' systems could not be
  measured; the Implementation Decisions above scope the fix to what was
  actually observed rather than assuming this list is complete everywhere.
- Spot-check systems named for verification once this fix lands: STC
  (`data/scan_cache/fbe54427b2bf7db0.pkl`) and Y-DOCs/TTPUR
  (`data/scan_cache/ee4df0cc3ec5f807.pkl`), in addition to IQCS.
