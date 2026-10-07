# 13 — A View Anchor includes the Razor URL helpers

**What to build:** On RTTalentDB, 73 controller actions have no forward chain
and no Program Screen in a backward chain. A view calls each of them, but the
Razor parser does not read the form of the call as a View Anchor. So no
Program Screen holds the action (ADR-0019), and the forward chain stops at
the program before the first call (reach 0).

Ticket 09 found these forms in the RTTalentDB source:

| Form | Actions | Example |
|---|---|---|
| `@Url.Action("Action", "Controller")` or `@Url.Action("Action")` in a `<script>` block | 60 | `Views/EmpJobDuty/EmpJobDutyMtn.cshtml:109` |
| `Html.BeginForm("Action", "Controller", ...)` | 5 | `Views/EvaluationSchedule/EvaluationScheduleMtn.cshtml:4` |
| A relative URL with no leading `/`, in a template literal, with a query or a route value | 4 | `Views/ResumeExperience/ResumeExperienceMtn.cshtml:644` |
| A URL in a `data-url` attribute | 1 | `Views/ResumePLApprove/ResumePLApproveMtn.cshtml:65` |
| A URL in a `.js` file that the view loads with `<script src>` | 1 | `wwwroot/js/traditional-assessment-common.js:602` |
| An action name that is not the method name: `[ActionName("X")]`, or the `Async` suffix that ASP.NET Core removes | 2 | `Controllers/TechnicianSkillController.cs:29` |

`probes/misses.json` gives each action with its reason and source line. The
reasons are `view_anchor_url_action`, `view_anchor_begin_form`,
`view_anchor_relative_url` and `action_name_differs`.

The glossary entry **View Anchor** names only `asp-action`, `asp-controller`,
`<form action>`, `asp-page` (determined) and a `/Controller/Action` string in
the view's own `<script>` block (`likely`). This ticket must first decide the
strength of each new form. `@Url.Action` and `Html.BeginForm` name the action
and the controller as arguments of a Razor helper, so they are not a guess.
A relative URL in a script is the same guess as the current `likely` form.

See ADR-0019, ADR-0044 and ticket 09.

**Blocked by:** None.

**Status:** needs-triage

- [ ] The glossary entry **View Anchor** names each new form and its strength
- [ ] A view that calls `@Url.Action("Action", "Controller")` gives a Program
      Screen that holds the action
- [ ] `@Url.Action("Action")` with no controller takes the controller of the
      view's folder
- [ ] `Html.BeginForm("Action", "Controller")` gives a View Anchor
- [ ] A Program Screen holds an action by its action name, so
      `[ActionName]` and the `Async` suffix match the view name
- [ ] The scan cache version rises, and a rescan of RTTalentDB uses the new
      format
- [ ] `check_misses.py` on RTTalentDB: remove each fixed action from
      `misses.json`, and record the new numbers of both probes here

**Notes:**

- The forward probe asks for the program by the controller name. Some actions
  of this ticket are held by the screen of another controller, so the probe
  still misses them after the fix: `UsersPicker` (4 actions, called from
  `TalentDBDepShoulderMtn` and others), `Public.GetJobTypeListByAuth` and
  `Public.GetTrialJobTypeListByAuth` (Shared partials), and
  `ResumeExperience.GetProjectExperienceData` (called from
  `AssessmentResult/ResumeAssessmentResult.cshtml`). Move them to the reason
  `held_by_another_screen`, and check that the backward probe reaches them.
- After the fix, `SkillClassificationPersonnelDetail.GetData` can meet the
  Dynamic SQL of `usp_RPT_SkillClassificationPersonnelDetailQry`, a known
  reason of ticket 09.
- A scan cache version rise makes each system skip until a local rescan. See
  ticket 05.
