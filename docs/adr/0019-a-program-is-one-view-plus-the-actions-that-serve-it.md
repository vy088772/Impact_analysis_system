# A Program Is One View Plus the Actions That Serve It

**Status:** Accepted
**Date:** 2026-09-09

## Context

A specification names a program by a bare code, such as `AgentMtn` or `JobDutyMtn`. `analyze_service` resolves that code to files by base name, and a WebForms repository makes that work: one program is one `.aspx` page plus its code-behind, and the page's file name is unique in the repository.

An MVC repository offers no such single file. Three real systems disagree about where the program's name even appears:

```
IQCS         AgentMtn     ->  Views/AgentMtn/AgentMtnView.cshtml     (the folder carries the name)
RTTalentDB   JobDutyMtn   ->  Views/JobDuty/JobDutyMtn.cshtml        (the file carries it; the controller does not)
                              JobDutyController.JobDutyMtn()
ETR          ImDecl, ImportDeclaration, ImportOverdueQry
                          ->  all three live in one ImportController
```

Two obvious rules were tried against this evidence and both failed. A name-prefix match finds RTTalentDB's view but never its `JobDutyController`, because `jobdutycontroller` does not start with `jobdutymtn`; loosening it to `JobDuty` then pulls in `JobDutyPersonnelSkillDetailController`, `JobDutySkillStatisticsController` and `TrialJobDutySkillQueryController`, which are three other programs. Taking the whole controller as the unit reports ETR's `ImportController` as one program when it serves three screens, and `ImportController` injects no service at all — it opens its own connection — so the "controller to service" edge that rule depends on does not exist there either.

## Decision

A Program Screen is one View file together with the set of actions that serve it. Its actions come from two sources: actions whose name equals the view name, and the View Anchors the view itself declares. The controller is a path used to reach those actions. It is not the unit of scope.

The program code resolves to that view through three entry points, tried in order: a `Views/{name}` folder, a view file whose base name is `{name}` (an optional `View` suffix allowed, for IQCS), and a `{name}Controller.cs` file.

## Consequences

- View Anchor extraction moves from a nice-to-have to a precondition. Without it a program has only its same-name actions, and every AJAX endpoint the screen calls disappears. The UI layer therefore cannot be deferred past the impact-chain layer.
- A shared AJAX controller with no view folder — `EnterpriseApp.AjaxController` is one — reaches a program only as a candidate anchor, at `likely`. Treating it as shared by every program would push its stored procedures into all twenty-two screens, which is noise, not an answer.
- One controller can appear in several Program Screens, and a screen holds only the actions it names on each controller it reaches. Both are consequences of scoping by view rather than by class. A screen therefore reaches its own controller and every controller its View Anchors name, and reports none of those controllers' other actions.
