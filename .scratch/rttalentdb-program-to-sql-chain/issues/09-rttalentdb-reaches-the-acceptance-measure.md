# 09 — RTTalentDB reaches the acceptance measure

**What to build:** Evidence that the forward and backward chains work on a
real MVC system. Each action that `truth.json` lists is either fully matched,
or it is on a named list of misses with a reason that the source confirms.

The measure is 227 of 227 RTTalentDB actions fully matched by
`compare_flow.py`, and the same for the backward probe of ticket 07, except
the named list. Known reasons:

- A stored procedure reached only through a helper parameter (ADR-0020).
- An ambiguous implementation (ticket 06).
- Unresolved Dynamic SQL (for example
  `usp_RPT_SkillClassificationPersonnelDetailQry`).

`truth.py` is a probe, not an oracle. It follows every implementer of an
interface, and the Local Implementer rule follows none of an ambiguous one.
Check each mismatch against the source before you put it on the list or fix
the chain.

See ADR-0044.

**Blocked by:** 05, 06, 07

**Status:** done (2026-10-07). The View Anchor misses move to ticket 13.

- [x] Each forward miss is on the list with a reason and a source location
- [x] Each backward miss is on the list with a reason and a source location
- [x] A miss with no known reason gets a fix, or a new ticket that names it
- [x] The final numbers of both probes are in this ticket

## Result (2026-10-07)

The probes ran against the main directory service on port 8800, scan cache
v46, after the merge of tickets 05 to 08. The output is the same, byte for
byte, as `probes/flow_after.json` and `probes/backward_after.json`.

```
compare_flow.py:   actions that should reach SP 227 | fully matched 114 | partial 6 | none 107
backward_flow.py:  actions with a table 227 | fully reached 120 | partial 6 | none 101
check_misses.py flow_after.json backward_after.json:
  listed misses 113 | backward misses 107 | every miss is on the list
```

The named list is `probes/misses.json`. Each entry gives the reason, the
stored procedures that the forward chain misses, and the source lines that
show the reason (relative to `RTTalentDB/RTTalentDB`). `probes/check_misses.py`
fails when a miss is not on the list, when a listed action is now fully
matched, or when the missed procedures change.

| Reason | Forward | Backward | Example source | Next step |
|---|---|---|---|---|
| `view_anchor_url_action`: the view calls `@Url.Action(...)` | 60 | 60 | `Views/EmpJobDuty/EmpJobDutyMtn.cshtml:109` | ticket 13 |
| `helper_parameter`: the procedure name goes to a helper parameter (ADR-0020) | 26 | 26 | `Services/TA/ResumeExperienceService.cs:96` | none (known reason) |
| `held_by_another_screen`: a Shared partial or another controller's view holds the action | 6 | 0 | `Views/Shared/_EmpPicker.cshtml:45` | probe limit |
| `view_anchor_relative_url`: a relative URL, template literal, `data-url` or `.js` file | 6 | 6 | `Views/ResumeExperience/ResumeExperienceMtn.cshtml:644` | ticket 13 |
| `view_anchor_begin_form`: the view calls `Html.BeginForm(...)` | 5 | 5 | `Views/EvaluationSchedule/EvaluationScheduleMtn.cshtml:4` | ticket 13 |
| `no_caller`: no view and no script calls the action | 5 | 5 | `Controllers/PersonalDataController.cs:37` | none |
| `runtime_url`: the script builds the URL at run time | 2 | 2 | `Views/MultiDimensional/MultiDimensionalQry.cshtml:61` | none |
| `action_name_differs`: `[ActionName]` or the `Async` suffix | 2 | 2 | `Controllers/TechnicianSkillController.cs:29` | ticket 13 |
| `dynamic_view`: the menu opens the action, and the view name is a run-time value | 1 | 1 | `Controllers/ResumeController.cs:27` | none |
| Total | 113 | 107 | | |

The three known reasons of this ticket:

- Helper parameter (ADR-0020): 26 actions. Each one reaches the service
  method, so the forward chain is not at reach 0. The 6 partial matches are
  all in this group.
- Ambiguous implementation (ticket 06): 0 actions in the measure.
  `Home.HomePage` and `ResumeQuery.GetResumePartial` report the call
  `strategy.BuildViewModelAsync` in `diagnostics`, and both are fully
  matched. The source shows that each strategy class reaches stored
  procedures through `ResumeService`. For example, `EmptyResumeStrategy`
  reaches `usp_RPT_ResumeInfoQry` (`Services/RPT/ResumeService.cs:50`), and
  `ResumeTraditionStrategy` reaches `usp_RPT_TraditionExperienceInfoQry`
  (`:70`). `truth.py` does not follow a
  call through a local variable (`ResumeService.cs:26`), so `truth.json`
  does not list them. The forward chain stops there by the Local Implementer
  rule, so the two sides agree, and the probe does not measure this case.
- Unresolved Dynamic SQL: 0 actions now.
  `SkillClassificationPersonnelDetail.GetData` is at reach 0 for the
  `view_anchor_url_action` reason. So the forward chain does not get to its
  Unresolved Dynamic SQL yet. Ticket 13 notes it.

**Notes:**

- The ticket text expected the known reasons to cover most misses. They do
  not. 87 forward misses have reach 0. The notes of ticket 05 gave one reason
  for them: no Program Screen holds the action (ADR-0019 scope).
  The source shows that a view calls 73 of the 87 actions. The Razor parser
  does not read the form of the call as a View Anchor. This is a gap, not a
  scope limit, so it goes to ticket 13 and not to the known list.
- The remaining 14 of the 87 are true limits: no caller (5), a run-time URL
  (2), a run-time view name (1), and an action that only another Program
  Screen holds (6).
- `no_caller` includes `JobType.GetValidJobType` and
  `JobType.GetInvalidJobType`. No view and no method calls them. The view
  calls `GetValidJobTypePartial` and `GetInvalidJobTypePartial`
  (`Views/JobType/JobTypeMtn.cshtml:164`, `:168`), and these actions call the
  service methods of the same name directly. `truth.py` reads each public
  method of a controller as an action.
- `held_by_another_screen` is a probe limit. The forward probe asks for the
  program by the controller name (`Public`), and no Program Screen has that
  name. The backward probe accepts a Program Screen of any view, so it
  reaches all 6 actions.
- Backward misses: the 107 actions are the forward list less the 6
  `held_by_another_screen` actions. No pair misses for a reason of the
  backward chain alone (see ticket 07).
- Not in the measure: 62 procedures that the forward chain reaches and
  `truth.json` does not list. `truth.py` is a probe, and this ticket did not
  check them.
- A scratch script built the list from the source. A
  `helper_parameter` entry gives, for each missed procedure, the first line in
  the source that passes its name to a helper and does not call
  `usp_ExecCmd*` directly.

## Code review (2026-10-07, `/code-review` on 0f8b40d)

Fixed:

- Spec: the note on `JobType.GetValidJobType` said that `JobTypeMtn` calls
  it. The source shows no caller. The note now names the two `Partial`
  actions that the view calls, and `misses.json` points at the declarations.
- Spec: the ambiguous implementation paragraph said that all three strategy
  classes reach both procedures. It now gives one example for each procedure.
- Spec: ticket 13 said that a relative URL with no leading `/` is a cause.
  The parser reads `'Public/EmpAutoCompleteByAuth'`. Ticket 13 now names the
  real causes: a template literal and a third segment.
- Spec: `check_misses.py` did not check the reason of a backward miss. A
  `held_by_another_screen` action that the backward probe misses now fails
  the check.
- Standards: two sentences in passive voice, one sentence over 25 words,
  "screen" alone (CONTEXT.md: avoid), the short form "the Dynamic SQL", and
  the "Next step" value `known`.
- Standards: in `check_misses.py`, the name `pairs` held no pairs, the truth
  rows were counted twice, and the docstring said to run the script from the
  probes directory.

Not changed:

- Standards: `check_misses.py` repeats the full match test of
  `compare_flow.py`. Each probe is a script that runs alone, as the other
  probes are.
- Standards: "reach" and "miss" as a noun and a verb. "Reach 0" is the
  probe's measure (`reachable_methods`) since ticket 03, and "fully matched"
  and "fully reached" are the probe output.
