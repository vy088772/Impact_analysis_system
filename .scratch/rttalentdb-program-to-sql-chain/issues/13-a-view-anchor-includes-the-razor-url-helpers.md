# 13 — A View Anchor includes the Razor URL helpers

**What to build:** On RTTalentDB, 72 controller actions have no forward chain
and no Program Screen in a backward chain. A view calls each of them, but the
Razor parser does not read the form of the call as a View Anchor. So no
Program Screen holds the action (ADR-0019), and the forward chain stops at
the program before the first call (reach 0).

Ticket 09 found these forms in the RTTalentDB source:

| Form | Actions | Example |
|---|---|---|
| `@Url.Action("Action", "Controller")` or `@Url.Action("Action")` in a `<script>` block | 60 | `Views/EmpJobDuty/EmpJobDutyMtn.cshtml:109` |
| `Html.BeginForm("Action", "Controller", ...)` | 5 | `Views/EvaluationSchedule/EvaluationScheduleMtn.cshtml:4` |
| A URL in a template literal (backticks), or with a route value as a third segment | 4 | `Views/ResumeExperience/ResumeExperienceMtn.cshtml:644` |
| A URL in a `data-url` attribute | 1 | `Views/ResumePLApprove/ResumePLApproveMtn.cshtml:65` |
| An action name that is not the method name: `[ActionName("X")]`, or the `Async` suffix that ASP.NET Core removes | 2 | `Controllers/TechnicianSkillController.cs:29` |

A relative URL with no leading `/` is not the cause: the parser reads
`'Public/EmpAutoCompleteByAuth'` (`Views/Shared/_EmpPicker.cshtml:45`). It
reads only a string in `'` or `"` with exactly two segments.

`probes/misses.json` gives each action with its reason and source line. The
reasons are `view_anchor_url_action`, `view_anchor_begin_form`,
`view_anchor_relative_url` and `action_name_differs`.

The one action in a `.js` file (`TraditionalAssessment.GetApproveComment`) moved
to ticket 15, because it needs a new view-to-script-file link.

The glossary entry **View Anchor** names only `asp-action`, `asp-controller`,
`<form action>`, `asp-page` (determined) and a `/Controller/Action` string in
the view's own `<script>` block (`likely`). This ticket must first decide the
strength of each new form. `@Url.Action` and `Html.BeginForm` name the action
and the controller as arguments of a Razor helper, so they are not a guess.
A relative URL in a script is the same guess as the current `likely` form.

See ADR-0019, ADR-0044 and ticket 09.

**Blocked by:** None.

**Status:** done (2026-10-07)

- [x] The glossary entry **View Anchor** names each new form and its strength
- [x] A view that calls `@Url.Action("Action", "Controller")` gives a Program
      Screen that holds the action
- [x] `@Url.Action("Action")` with no controller takes the controller of the
      view's folder
- [x] `Html.BeginForm("Action", "Controller")` gives a View Anchor
- [x] A Program Screen holds an action by its action name, so
      `[ActionName]` and the `Async` suffix match the view name
- [x] The scan cache version rises, and a rescan of RTTalentDB uses the new
      format
- [x] `check_misses.py` on RTTalentDB: remove each fixed action from
      `misses.json`, and record the new numbers of both probes here

**Notes:**

- The forward probe asks for the program by the controller name. For some
  actions of this ticket, only the Program Screen of another controller's view
  holds the action. So the probe still misses them after the fix: `UsersPicker` (4 actions, called from
  `TalentDBDepShoulderMtn` and others), `Public.GetJobTypeListByAuth` and
  `Public.GetTrialJobTypeListByAuth` (Shared partials), and
  `ResumeExperience.GetProjectExperienceData` (called from
  `AssessmentResult/ResumeAssessmentResult.cshtml`). Move them to the reason
  `held_by_another_screen`, and check that the backward probe reaches them.
- After the fix, the forward chain of
  `SkillClassificationPersonnelDetail.GetData` can get to the Unresolved
  Dynamic SQL of `usp_RPT_SkillClassificationPersonnelDetailQry`. Ticket 09
  lists this as a known reason.
- A scan cache version rise makes each system skip until a local rescan. See
  ticket 05.

## Result (2026-10-07)

Decisions for the strength of each new form:

| Form | Strength |
|---|---|
| `@Url.Action("A", "C")`, `@Url.Action("A")`, `Html.BeginForm("A", "C")`, `Html.BeginForm("A")` | determined |
| A URL in backticks, a route value as third segment, a `data-url` value | `likely` |

A helper with no controller argument gives an anchor with no controller, so the
screen's own controller serves it (the same rule as `asp-action` alone). The
third segment must be an identifier, a number or `${...}`, so a path such as
`lib/jquery/jquery.min.js` is no anchor.

The action name: `MethodInfo.action_name` holds `[ActionName("X")]`, or the
method name without the `Async` suffix. `controller_actions` carries
`(method name, action name)`. A screen matches the view name and each anchor by
the action name, and reports the action by its method name, because the call
graph uses the method name.

The probes ran on a private service (port 8802, private scan cache v47, all four
RTTalentDB roots rescanned). Output: `probes/flow_ticket13.json` and
`probes/backward_ticket13.json` (`flow_after.json` and `backward_after.json`
stay as ticket 09 left them).

```
compare_flow.py:   actions that should reach SP 227 | fully matched 178 | partial 6 | none 43   (was 114 / 6 / 107)
backward_flow.py:  actions with a table 227 | fully reached 191 | partial 6 | none 30            (was 120 / 6 / 101)
check_misses.py:   listed misses 49 | every miss is on the list
```

`misses.json` went from 113 to 49 entries. Seven entries moved to
`held_by_another_screen` (the ticket says six; the list has seven: four
`UsersPicker`, `Public.GetJobTypeListByAuth`, `Public.GetTrialJobTypeListByAuth`,
`ResumeExperience.GetProjectExperienceData`). The backward probe reaches all 13
`held_by_another_screen` actions. `ResumeExperience.GetExpContentByPoint` has its
anchor now, and its miss has a new reason, `helper_parameter`: the service passes
`"dbo.usp_SYS_DataBring"` to the private helper `ExecuteAndMapList`
(`Services/TA/ResumeExperienceService.cs:243`). `TraditionalAssessment.GetApproveComment`
stays on the list for ticket 15.

Scan cache version: 46 to 47. The main service on port 8800 reloads with the new
code and reads each scan as stale until a local rescan (see ticket 05).

Full suite: 1840 passed (without `test_search_roles.py` and `test_sp_tables.py`,
which fail at collection with no SQL Server, before this change too).

## Review notes (2026-10-07, /code-review of 6fd7fda)

Fixed in the review commit:

- A call in a Razor comment (`@* *@`) or an HTML comment gave a determined anchor.
  The URL helper pattern now runs on the content without both comment forms.
- `[HttpPost, ActionName("X")]` (two attributes in one bracket) was not read.

Left as is, on purpose:

- A bare string in `Url.Action("A", "x")` is always the controller; a named-argument
  call (`Url.Action(action: "A", controller: "C")`) gives no anchor. Not in RTTalentDB.
- A multi-line `[ActionName]`, or a `//` comment between the attribute and the method,
  is not read. Not in RTTalentDB.
- A three-segment string such as `/foo/bar/baz` gives a `likely` candidate. The
  Program Screen keeps only a candidate that names a declared action.
- `Foo` and `FooAsync` in one controller: both route to `Foo`; the screen reports
  the first method that matches an anchor. ASP.NET Core also reports this as ambiguous.
- ADR-0019 line 36 still says `likely` for a script URL. The glossary is the source
  for the new forms; update the ADR when a ticket changes its decision.
- Smells (judgement calls): the `(method, action name)` tuple wants a small type;
  the three `controller, action` anchor blocks in `razor_parser.py` repeat;
  `_exact_controller_action` now accepts a third segment. Not changed.

**Code review follow-up (2026-10-08, ticket 18):**

- The parser strips Razor and HTML comments before it matches a URL helper. The
  brief did not ask for this. A helper inside a comment is dead code, so it
  gives no anchor (`test_a_helper_call_inside_a_razor_or_html_comment_is_no_anchor`).
- A helper whose second argument is a variable, such as
  `Url.Action("A", controllerName)`, gave a determined anchor with the controller
  of the view's folder. Now it gives no anchor. On all 1357 helper calls of the
  cached systems, the old and new patterns give the same result.
- The three `controller, action` anchor blocks share `_controller_action_anchor`.
- ADR-0044 now says that a URL helper in a `<script>` block is determined.

## Comments

> *This was generated by AI during triage.*

## Agent Brief

**Category:** enhancement
**Summary:** The Razor parser turns `@Url.Action`, `Html.BeginForm` and four
related URL forms in a view into View Anchors, so a Program Screen holds the
action.

**Current behavior:**
`RazorParser` reads a View Anchor only from `asp-action`, `asp-controller`,
`asp-page`, `<form action>`, and a two-segment string in a `<script>` block.
`@Url.*` and `Html.*` calls are recorded as helpers, never as anchors.

**Desired behavior:**
- `@Url.Action("A", "C")` gives a determined anchor with action A and controller C.
- `@Url.Action("A")` with no controller takes the controller of the view's folder.
- `Html.BeginForm("A", "C", ...)` gives a determined anchor.
- A URL in a template literal, with a route value as a third segment, in a
  `data-url` attribute, or as a relative URL with no leading `/`, gives a
  candidate anchor at `likely`. The two strengths stay separate.
- A Program Screen holds an action by its action name. `[ActionName("X")]`
  and the `Async` suffix that ASP.NET Core removes must both match the view name.

**Key interfaces:**
- `code_analyzer/razor_parser.py`: the determined and candidate anchor extractors.
- The Program Screen action match (`ProgramScreen.actions`).
- `CONTEXT.md` entry **View Anchor**: name each new form and its strength.
- `service/scan_store.py` `_CACHE_VERSION`: raise it.

**Acceptance criteria:** the checklist above, unchanged.

**Out of scope:**
- The action in a `.js` file (ticket 15).
- Actions in the `helper_parameter`, `no_caller`, `runtime_url` and
  `dynamic_view` reasons of `misses.json`.
- Making the forward probe find actions that another controller's screen holds.
  Move those six to `held_by_another_screen` and check the backward probe.
