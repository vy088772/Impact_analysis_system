# 10 — A Program Screen resolves to a view and its same-name actions

**What to build:** A specification program code resolves to one Program Screen: the view it names
and the actions whose name matches it (ADR-0019).

Base-name matching cannot do this. Across the measured repositories the program
name sits sometimes on the view folder, sometimes on the view file, and the
controller that serves it may carry an entirely different name. The existing
loose match also absorbs longer names, so a shorter program name swallows a
longer, unrelated one.

Resolution tries three entry points in order, and searches Area-qualified paths
the same way. WebForms program resolution is untouched and keeps its existing
path.

**Blocked by:** 04.

**Status:** done

- [x] A program code naming a view folder resolves to that folder's views.
- [x] A program code naming a view file resolves to that file, with an optional trailing `View` in the file name allowed.
- [x] A program code naming a controller file resolves through it.
- [x] An Area-qualified program code resolves, and two Areas holding same-named views do not collide.
- [x] A match requires the whole name; a program code never matches a longer name that merely contains it.
- [x] A resolved Program Screen holds one view and the actions whose name equals the view name.
- [x] One controller serving three views yields three Program Screens, each holding only its own actions.
- [x] A program code matching nothing is reported as not found.
- [x] WebForms program resolution is unchanged, verified against the existing system.

## Note

**New module `service/program_screen.py`** (pure, no I/O): `ProgramScreen`
(program code, view path, view name, Area, controller path, action names) and
`resolve_program_screens(code, view_paths=, controller_actions=)`. It takes
paths and a file-to-method-names mapping, so it never touches the scan result
shape. Area comes from an `Areas/{X}/` path segment; a program code may carry
one as `Admin/Summary`.

The three entry points, tried in order:

1. A view folder whose name equals the code — every view in it is one screen.
2. A view file whose base name equals the code, with a trailing `View` allowed
   on the file (IQCS's `Views/AgentMtn/AgentMtnView.cshtml`).
3. A `{code}Controller.cs` — the views it reaches *the way MVC itself looks a
   view up*: `Views/{code}/{action}` then `Views/Shared/{action}`, inside the
   controller's own Area. A first draft searched every view in the Area, which
   made every `Index.cshtml` in the repository a screen of every controller
   declaring an `Index` action; a Spec review sub-agent caught it.

A screen's controller is the one its view folder names. When the folder names
none, the screen binds the *one* controller of its Area that declares an action
of the view's name — the ticket's own "the controller that serves it may carry
an entirely different name". Two such controllers bind neither, and the screen
reports no action rather than guessing.

The optional trailing `View` is allowed **only** where the spec allows it: on
the view file, against the program code. It is not extended to action names —
an action serves a view when the two names are equal outright.

**`analyze()` restructure.** `_ProgramResolution` is the per-program unit of
analysis: either one Program Screen or the legacy base-name match. One
requested code can now yield several `ProgramAnalysis` entries (one per screen,
same `program`, different `file`), so `not_found` moved to "no resolution
reported anything" instead of a single in-loop check. For a screen, `file` is
the **view** — the screen is the view (ADR-0019); the controller stays visible
through each `methods` entry's `class`.

`resolution.owns_method()` narrows methods, invocations, table relations, call
chains, snippets and related programs to the screen's actions.
`_build_program_execution_paths` gained an `entry_methods` parameter so the
narrowing happens *before* the paths are built — post-filtering the compact
payload left `total_paths`/`returned_paths`/`omitted_paths` describing paths the
program did not report (Standards review caught this).

**The fallback rule.** Where Razor views exist and a code resolves to no
screen, the legacy substring match must not run — `JobDuty` would otherwise
absorb `JobDutyMtnController.cs` and break the whole-name criterion. The
fallback is therefore allowed only when the code names a WebForms page, or
names one C# file *outright* (whole base name). A repository with no Razor
view at all never enters the new path at all.

**WebForms verification (criterion 9).** Scanned three real Y-DOCs roots and
compared the old `_file_matches` result against `_program_resolutions` for every
`.aspx` program name: ATV 5/5, Response 7/7, TTRDQ 134/134 unchanged, and no
Program Screen was ever constructed (`razor_results` is empty in all three).

**Left to ticket 13.** A Program Screen holds only its same-name actions here.
`ProgramScreen.controller_path` is one string and `owns_file()` compares only
it, so ticket 13 — which must attribute an action on a *second*, shared
controller reached through a candidate anchor — will have to widen both
`ProgramScreen` and `_ProgramResolution` to a set of controllers.

**Tests:** `tests/test_program_screen_resolution.py`, 18 cases, all at the
`analyze_service` seam the spec names. Full suite 761 passed / 11 failed, the
same pre-existing baseline names as before this ticket.
