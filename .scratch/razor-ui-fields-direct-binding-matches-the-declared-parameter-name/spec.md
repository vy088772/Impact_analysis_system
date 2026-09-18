# Razor `ui_fields` Direct Binding Matches the Declared Lambda Parameter

Status: ready-for-agent

Companion to `.scratch/razor-ui-fields-cover-html-for-helpers/`, which taught
`_extract_ui_fields` to recognize `@Html.<Method>For(<lambda>, ...)` calls.
This spec narrows one rule inside that same extraction — which lambda
bindings count as "direct" enough to earn a `data_field` — found while
reviewing that spec's already-merged implementation. The two are unrelated
in scope to the parent spec's own remaining Out of Scope items and are
tracked separately rather than reopening the parent's closed tickets.

## Problem Statement

`_extract_ui_fields`'s direct-binding check compares a `@Html.<Method>For`
call's bound expression against a literal `m` or `Model` (case-sensitive),
independent of what the lambda's own declared parameter is actually named.
A view that consistently binds through a differently spelled parameter —
most commonly the scaffolded `model` (lowercase) — never earns a
`data_field`, even though the binding is exactly as direct and safe as
`m.Property`. This is not hypothetical: across
`data/repos/System_Dept_1`'s Razor views (IQCS, RTTalentDB, TOPCSCY, and
other sub-projects), `model => model.<Property>` and `o => o.<Property>`
already appear 1263 times combined. 30 of those are a single direct
property access — the same shape `m.Property` is — and today none of them
earn a `data_field`; the analyst reading `ui_fields` for these fields gets
the raw bound expression instead of the caption `razor_display_field_resolver`
would otherwise supply.

## Solution

Replace the hardcoded literal-`m`/`Model` comparison with a comparison
against the lambda's own declared parameter, captured from the same match
that already recognizes the `@Html.<Method>For(...)` call. A binding is
direct when the body's leading identifier equals that declared parameter —
whatever it is spelled: `m`, `model`, `o`, or any other name a scaffolder or
developer chose — or when it is the literal `Model`, the ambient
page-model property Razor exposes independent of any lambda and distinct
from the lambda's own parameter. Any other leading identifier — a `foreach`
loop variable closed over instead of the declared parameter, for instance —
still contributes an entry with only the raw bound expression as `text`,
exactly as today. The existing single-property-only shape restriction (no
collection index, no further `.` after the first property) is unchanged and
continues to gate out `model.Items[0].Property` and `model.Query.JobTypeID`
the same way it already gates out `Model.Items[0].Property` today.

Since every declared parameter name now participates automatically, the
separate hardcoded literal `m` is dropped — a differently spelled but
consistently used parameter no longer needs its own name added to a list.

## User Stories

1. As an analyst, I want `@Html.DisplayNameFor(model => model.Property)` to
   earn the same `data_field` that `@Html.DisplayNameFor(m => m.Property)`
   does today, so that a scaffolder's parameter-naming choice never changes
   whether a field's real caption gets resolved.
2. As an analyst, I want the same recognition for any consistently-used
   declared parameter name, not only `m` and `model`, so that a view using
   `o`, `vm`, or any other spelling still resolves its captions.
3. As an analyst, I want `@Html.DisplayFor(model => Model.Property)` to keep
   earning a `data_field` exactly as it does today, independent of what the
   lambda's declared parameter is actually named, because `Model` names the
   view's own model regardless of the lambda.
4. As an analyst, I want a binding through a collection index
   (`model.Items[0].Property`) or a multi-level property chain
   (`model.Query.JobTypeID`) to keep falling back to raw `text` with no
   `data_field`, whatever the parameter is named, so this fix never resolves
   a binding the existing safety rule was built to exclude.
5. As an analyst, I want a binding through an identifier that is neither the
   call's own declared parameter nor the literal `Model` — a `foreach` loop
   variable closed over instead, for instance — to keep falling back to raw
   `text` with no `data_field`, so the `modelItem => item.UserName` scaffold
   case the parent spec already excludes stays excluded.
6. As a maintainer, I want the direct-binding check to read the declared
   parameter from the same regex match that already recognizes the
   `@Html.<Method>For(...)` call, so there is one parsing pass, not two.
7. As a maintainer, I want the literal `Model` special case kept as the one
   remaining hardcoded exception — because it is not a parameter name, it is
   an ambient identifier — while the `m` special case is removed as
   redundant once matching is against the actual declared parameter.
8. As a maintainer, I want this fix to apply uniformly to every scanned
   system's Razor views, so a system other than the ones already measured
   gets the same coverage without any system-specific change.
9. As a reviewer, I want a test asserting a direct binding through a
   declared parameter other than `m`/`Model` (e.g.
   `model => model.Property`) produces a `data_field`, so the fixed case is
   under test rather than merely described.
10. As a reviewer, I want a test asserting the literal-`Model` case still
    resolves regardless of the declared parameter's own spelling (e.g.
    `model => Model.Property`), so today's already-correct behavior is
    locked in rather than assumed.
11. As a reviewer, I want the existing tests in
    `test_razor_parser_ui_fields.py` — including the
    `modelItem => item.UserName` scaffold-exclusion case — to keep passing
    unchanged, so this fix is proven additive, not a quiet behavior change
    to an already-correct case.
12. As a reviewer, I want a test asserting a collection-indexed binding and
    a multi-level binding through a non-`m`/`Model` parameter (e.g.
    `model => model.Items[0].Property`, `model => model.Query.JobTypeID`)
    still produce raw `text` with no `data_field`, so the safety rule's
    independence from parameter spelling is under test.
13. As a maintainer, I want the scan-cache version convention incremented
    again, since already-scanned views using a non-`m`/`Model` parameter
    change `ui_fields` shape under this fix.

## Implementation Decisions

- The direct-binding check's literal `m`/`Model` alternation is replaced by
  a comparison against the declared lambda parameter captured from the same
  match already used to recognize the `@Html.<Method>For(...)` call — that
  match gains a capturing group for the parameter identifier where today it
  is matched but discarded.
- A binding is direct — and contributes `data_field` — when its leading
  identifier equals either that captured declared parameter (exact,
  case-sensitive match) or the literal string `Model`. Any other leading
  identifier keeps the entry's raw bound expression as `text` and
  contributes no `data_field`.
- The existing anchored, single-property-only shape (no further `.`, no
  `[`) is unchanged and is applied against whichever of the two accepted
  prefixes matched.
- The literal `m` special case is removed; it is subsumed by comparing
  against the declared parameter, since a call declaring `m` as its
  parameter matches under the new rule automatically.
- No change to `razor_display_field_resolver`, the HTML-Helper counting
  pass, or any other extraction pass — this is scoped entirely to the
  direct-binding check inside the `@Html.<Method>For(...)` handling.
- No per-system configuration; the fix applies uniformly to every scanned
  system's Razor views, the same principle the parent spec already
  established for Helper recognition itself.
- The scan-cache version convention requires another increment, since
  `ui_fields` contents change shape for any already-scanned view using a
  non-`m`/`Model` declared parameter for a direct single-property binding.

## Testing Decisions

A good test here asserts what `ui_fields` contains for given markup, never
which internal branch of the parser produced it — the same principle the
parent spec's own tests already follow.

**Seam.** `RazorParser().parse_file()` → `.ui_fields`, the exact seam
`tests/test_razor_parser_ui_fields.py` already exercises for the parent
spec's Helper tests. No new seam is needed.

- One test asserting a direct binding through a declared parameter other
  than `m`/`Model` (e.g. `@Html.DisplayNameFor(model => model.EmpID)`,
  drawn from real markup found in `RTTalentDB`) produces a `data_field`.
- One test asserting the literal-`Model` case resolves independent of the
  declared parameter's spelling (e.g.
  `@Html.DisplayNameFor(model => Model.UserName)`, the shape already
  observed in real `RTTalentDB` usage).
- One test asserting a multi-level binding through a non-`m`/`Model`
  parameter (e.g. `@Html.DisplayNameFor(model => model.Query.JobTypeID)`,
  drawn from real markup) still produces raw `text` with no `data_field`.
- One test asserting a collection-indexed binding through a non-`m`/`Model`
  parameter (e.g.
  `@Html.DisplayNameFor(model => model.ResultList[0].UserID)`, drawn from
  real markup) still produces raw `text` with no `data_field`.
- The existing tests in `test_razor_parser_ui_fields.py`, including the
  `modelItem => item.UserName` scaffold-exclusion test from the parent
  spec, continue to pass unchanged.

## Out of Scope

- Resolving a collection-indexed or multi-level binding to actual display
  text, for any parameter name — unchanged from the parent spec's own Out
  of Scope.
- Any change to `razor_display_field_resolver`.
- Re-litigating the parent spec
  (`.scratch/razor-ui-fields-cover-html-for-helpers/`) or its already-closed
  tickets; this spec amends only the direct-binding rule and leaves that
  spec's own record as written.
- Adding recognition for any `@Html`/`@Url`/`@Ajax` Helper beyond the five
  the parent spec already scoped to.

## Further Notes

- Found during a code-review pass over the parent spec's already-merged
  implementation (commits `4bc7d1b`, `6626c15`), not during the parent
  spec's own drafting or review. The parent spec's own Implementation
  Decision — "Only a direct binding — `m.Property` or `Model.Property` —
  earns a `data_field`" — was accurate to what it specified and shipped; it
  is superseded by this spec rather than having been wrong when written.
- Measured impact across `data/repos/System_Dept_1` (all sub-projects —
  IQCS, RTTalentDB, TOPCSCY, and others), 912 `.cshtml` files: 1263
  occurrences of a Helper call whose declared parameter and body's leading
  identifier match each other and are neither `m` nor `Model` — 1256
  spelled `model`, 7 spelled `o`. Of those, 30 are a single direct property
  access (this fix's actual target), 18 are multi-level, and 1215 are
  collection-indexed (both of the latter two must and do keep falling back
  to raw `text`).
- No occurrence of `model.addcond.ReceiveList` — the parent spec's own
  nested-binding example — was found in the scanned repos; the multi-level
  examples actually present (`model.Query.JobTypeID`,
  `model.Save.ExperienceItem`, `o.Header.ShopLotNo`) serve as this spec's
  test fixtures instead.
