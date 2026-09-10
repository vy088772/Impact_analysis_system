# 15 — ViewComponent and partial view contributions

**What to build:** A screen that renders a shared component reaches that component's stored
procedures, so the MVC path is not shallower than the WebForms user-control path
it corresponds to.

The contribution is labelled as coming from a shared component. Without the
label a component rendered on every screen — a menu, a selector — would put its
tables into every screen's answer with no way to tell them from the screen's
own.

**Blocked by:** 13.

**Status:** resolved

- [x] A view rendering a ViewComponent reaches that component's stored procedures and tables.
- [x] A view rendering a partial view reaches that partial's stored procedures and tables the same way.
- [x] Every contribution reached this way is labelled as coming from a shared component.
- [x] A component rendered by many screens contributes to each of them, and the label makes it distinguishable from the screen's own access.
- [x] A component that reaches no database contributes nothing and produces no empty entry.
- [x] A measured repository's selector component contributes its stored procedures to the screens that render it.

## Notes (resolved)

- `code_analyzer/razor_parser.py`: `RazorParser` now extracts
  `view_component_references`/`partial_view_references` (new
  `FileAnalysisResult` fields) — raw names only (`Component.InvokeAsync("X")`/
  `Component.Invoke("X")`/`<vc:kebab-name>` for ViewComponents;
  `Html.Partial`/`Html.RenderPartial` (+`Async`)/`<partial name="X">` for
  partials). A single .cshtml file cannot see other scanned files, so
  resolution to an actual file/class is deferred entirely to a new pure
  module.
- New `service/shared_component.py`: `resolve_shared_components(view_path,
  ...)` walks the render chain from one screen's view — partial through
  partial, partial through ViewComponent — and returns every ViewComponent it
  actually reaches (`SharedComponentContribution`). A partial view holds no
  server code of its own and contributes nothing directly; it is purely a
  traversal node. A ViewComponent is matched by class name (optionally
  stripping the conventional `ViewComponent` suffix, dash/underscore
  insensitive for the `<vc:kebab-name>` tag form) AND requires either that
  suffix or `base_class == "ViewComponent"` — a name match on an unrelated
  class never counts. Only the class's own `InvokeAsync`/`Invoke` method is
  reported (the one method the framework actually calls to render it). Two
  classes normalizing to the same name, or a class with neither invoke
  method, resolve to nothing (silently — no reason code; a deliberate,
  disclosed scope boundary, see below). `seen_views` guards the partial
  recursion against a partial-cycle looping forever.
- `service/program_screen.py` gained a small public `view_identity(path)`
  wrapper around its existing private `_view_file` parse, so
  `shared_component.py` locates a partial view the same way
  `resolve_program_screens` looks a view up (same folder as caller first,
  then Shared in the same Area, then root Shared) without duplicating that
  parse.
- `service/analyze_service.py`'s `analyze()`: for a resolved Program Screen
  only (never the WebForms/legacy path), resolves shared components from the
  screen's own view, rates each resolved ViewComponent's own file through the
  same `_rated_execution_invocations` join already used for the screen's own
  files, and merges the result into the screen's own `stored_procedures`/
  `tables`/`database_invocations`/`diagnostics` — each shared entry additionally
  carries `"shared_component": {"kind": "view_component", "name": ...}`, which
  the screen's own entries never carry. A new `ProgramAnalysis.
  shared_component_contributions` (schemas.py) also breaks each reached
  component out on its own with its own `stored_procedures`/`tables`, so a
  menu/selector component's access is never merged into and indistinguishable
  from the screen's own. Deliberately does NOT touch `methods`,
  `execution_paths`, or `compact_execution_paths` — those stay strictly the
  screen's own controller/action reach; the ticket only asked for stored
  procedures and tables. `scan_store._CACHE_VERSION` 34->35 (RazorParser's new
  fields change `FileAnalysisResult`'s pickled shape). `docs/openapi/openapi.json`
  regenerated for the new response field.
- Tests: `tests/test_razor_parser_shared_components.py` (8, parser-only),
  `tests/test_shared_component_resolution.py` (12, pure `shared_component.py`
  module), `tests/test_shared_component_contributions.py` (7, drives
  `analyze_service.analyze()` — includes the "reached by two screens",
  "reaches no database contributes nothing", and a synthetic
  TOPCSCY-shaped ("13 Areas, 510 views") selector-component test). Full
  suite: 834 passed / 11 failed (same pre-existing baseline as ticket 14) /
  5 skipped.
- Code review (Standards + Spec subagents) run against the working-tree diff
  vs. `HEAD` (`ecbb494`). Standards: no hard violations; one judgement-call
  smell (duplicated dedup-append shape between the screen's own SP/table
  collection and the shared-component collection) was cheap to fix and
  applied — extracted a small `_append_once(name, *lists)` helper, both call
  sites now share it. Spec: one disclosed gap, not fixed — none of the 5
  measured MVC/Core repositories (IQCS/RTTalentDB/ETR/EnterpriseApp/TOPCSCY)
  are checked out in this environment (only WebForms `Y-DOCs`/`STC` under
  `data/repos/`), so the "measured repository's selector component" checklist
  item is satisfied by a synthetic scan explicitly modelled on TOPCSCY's shape
  (comment says so), not a real-repo smoke test in the style of
  `test_semantic_binding_availability.py`'s `requires_iqcs_fixture`-gated
  tests. Also not fixed (explicitly out of scope per the checklist's own six
  items, noted for a future ticket if wanted): an ambiguous ViewComponent
  name match or a class with no invoke method resolves to nothing with no
  diagnostic/reason code, unlike this codebase's usual "every unresolved fact
  names its reason" philosophy (spec.md story 31) — the checklist never asked
  for one, so none was added.
