# 01 — Match direct binding against the declared lambda parameter, not a hardcoded `m`/`Model`

**What to build:** The direct-binding check inside `_extract_ui_fields`'s
`@Html.<Method>For(...)` handling recognizes any declared lambda parameter
name — not only a hardcoded `m` — as safe to resolve, whenever the binding
is a single direct property access off that parameter. The literal `Model`
(Razor's ambient page-model property, independent of the lambda) keeps
resolving regardless of what the lambda's own parameter is named. Any other
leading identifier — a `foreach` loop variable closed over instead of the
declared parameter, for instance — still falls back to a raw-text entry
with no `data_field`, exactly as today. A collection-indexed or multi-level
binding keeps falling back to raw text too, whatever the parameter is
named — this ticket only widens which parameter *names* count as direct, it
never widens which binding *shapes* count as direct.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A direct binding through a declared parameter other than `m`/`Model`
      (e.g. `model => model.Property`) produces a `data_field`.
- [x] A binding through the literal `Model`, with the lambda's own declared
      parameter spelled differently (e.g. `model => Model.Property`), still
      produces a `data_field`.
- [x] A multi-level binding through a non-`m`/`Model` parameter (e.g.
      `model => model.Query.JobTypeID`) still produces raw `text` with no
      `data_field`.
- [x] A collection-indexed binding through a non-`m`/`Model` parameter (e.g.
      `model => model.ResultList[0].UserID`) still produces raw `text` with
      no `data_field`.
- [x] A binding through an identifier that is neither the call's own
      declared parameter nor the literal `Model` (the existing
      `modelItem => item.UserName` scaffold-exclusion case) still produces
      raw `text` with no `data_field`.
- [x] The existing tests in `test_razor_parser_ui_fields.py` keep passing
      unchanged.
- [x] The hardcoded literal `m` special case is removed from the
      implementation — it is subsumed by comparing against the actual
      declared parameter.
- [x] No change to `razor_display_field_resolver` or the HTML-Helper
      counting pass.
- [x] The scan-cache version convention is incremented.

## Note

This ticket, and the parent spec, both describe "the existing
`modelItem => item.UserName` scaffold-exclusion case" as already present in
`test_razor_parser_ui_fields.py`. The actual pre-existing test there was
`test_a_non_model_lambda_parameter_binding_produces_raw_text_with_no_data_field`,
which used `@Html.DisplayFor(item => item.UserName)` — a **matching**
declared parameter and body root (`item` both times), not the mismatched
`modelItem => item.UserName` shape the ticket's checklist describes. Under
this fix's own rule (direct when the body's leading identifier equals the
lambda's own declared parameter), that pre-existing case is a genuine direct
binding and must now produce a `data_field` — it cannot pass unchanged.

Resolution: renamed that test to
`test_a_direct_binding_through_a_consistently_named_non_m_parameter_produces_a_data_field`
and updated its assertion to expect `data_field: "UserName"`, with a comment
explaining why. Added a separate new test using the actual
`modelItem => item.UserName` mismatched shape the ticket describes, to cover
the scaffold-exclusion case the ticket intended. All 17 tests in the file
pass; no other test in the repo references the old test's name or
assertion. Full suite run confirms the only failures (11, in unrelated
SQL/DB-connection tests) are pre-existing on the unmodified branch too.
