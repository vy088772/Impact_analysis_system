# 13 — A Program Screen gains its anchored actions

**What to build:** A Program Screen's action set is complete: the actions whose name matches the
view, plus the actions its View Anchors name.

Ticket 10 delivers the first half. Without the second, every endpoint a screen
calls asynchronously is missing from its impact chain, including endpoints that
live on a shared controller with no view folder of its own. Such a shared
endpoint reaches a screen only through a candidate anchor, at `likely`, and is
reported that way rather than being attributed to every screen.

**Blocked by:** 10, 12.

**Status:** resolved

- [x] A Program Screen holds the actions named by its determined View Anchors.
- [x] A Program Screen holds the actions named by its candidate View Anchors, carried at `likely`.
- [x] An action reached only through a candidate anchor is reported with that strength, never as determined.
- [x] An action on a shared controller with no view folder reaches a screen only through that screen's own anchors.
- [x] A controller appearing in two Program Screens contributes only the actions each screen anchors.
- [x] The measured repository's AJAX detail query appears in its screen's impact chain.

## Note

**`service/program_screen.py`.** A screen's actions become `ScreenAction`
records — a name, the controller that declares it, and a strength — instead of
bare names. `resolve_program_screens` gained `determined_anchors=` and
`candidate_anchors=`, two arguments rather than one, because the two strengths
are never merged even at the boundary. An action's strength is `determined`
when the view's own name or a markup-layer anchor named it, `likely` when only
a candidate anchor did; the same action reached both ways keeps the stronger,
so a candidate never downgrades a proven reach.

An anchor reaches a controller by whole name inside the view's own Area, and
falls back to a controller outside every Area when the Area declares none of
that name — the route ADR-0019's shared AJAX controller is reached by. This
also removed ticket 10's Area pre-filter on the controller list: both entry
points already compare a controller's Area to its view's, so the pre-filter was
redundant for resolution and was blocking every anchor an Area view makes.

An anchor whose action no controller declares, and a page anchor (which names
no controller action at all — ticket 14 owns that mechanism), each contribute
nothing. The screen reports the actions it can reach, never a name it cannot.

**`service/analyze_service.py`.** A screen's `matched_files` is now the union of
every controller its actions sit on, its own first, so a shared controller with
no view folder enters the analysis only through the anchors that name it.
Method ownership moved from the name alone to `owns_action(file, name)`: one
controller can hold an action of this screen beside an action of another
screen's, so a name that matches on the wrong controller is not this screen's.
`_build_program_execution_paths` takes an `entry_filter` predicate rather than a
name set for the same reason. `ProgramAnalysis.methods` entries carry
`strength` for a Program Screen; the WebForms path reports methods exactly as
before.

**Deliberately not done.** A `likely` action's stored procedures are not
re-rated. `evidence` on a Database Invocation says how well the *invocation*
resolved, and the anchor strength says how well the *screen-to-action edge* is
known. Folding one into the other would repeat the alias confusion ticket 03 of
`collapse-wrapper-evidence-aliases` had to untangle. The strength is reported
where the action is reported.

**Review.** Two-axis (Standards + Spec) review. Fixed from it: the Area
pre-filter above (Spec — it broke this ticket's own fourth checklist item in
any Area repository); a name-only fallback that let a screen absorb a same-named
action on its own controller when it anchors that name elsewhere (Spec — it
re-opened the leak ticket 10 closed, now covered by
`test_the_anchored_name_never_admits_the_same_name_on_the_screens_own_controller`);
an unused `ProgramScreen.action_names` property; a defensive `getattr` for
fields ticket 12 already declares; a test helper that silently ignored anchors
passed beside a parsed source. Also fixed: CONTEXT.md and ADR-0019 both still
said "one Program Screen never spans two controllers", which this ticket makes
false — the controller is still never the unit of scope, but a screen reaches
every controller its anchors name and reports none of their other actions.

7 tests added to `tests/test_program_screen_resolution.py` (25 in file). Full
suite: 801 passed / 11 failed (the same pre-existing baseline as tickets 11 and
12) / 5 skipped.
