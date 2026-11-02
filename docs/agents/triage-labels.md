# Triage labels

Each open issue has one state label from the table below. Remove the old state label when you add a new one. The `spec` label is not a state label, so a spec issue can also have one state label.

| Label in mattpocock/skills | Label in our tracker | Meaning | Next state |
| --- | --- | --- | --- |
| `needs-triage` | `needs-triage` | A person must decide the scope before work starts. | `ready-for-agent`, `ready-for-human`, `needs-info` or `wontfix` |
| `needs-info` | `needs-info` | The reporter must supply more information. | `needs-triage` |
| `ready-for-agent` | `ready-for-agent` | An agent can start the work now. | `in-review` |
| `ready-for-human` | `ready-for-human` | A person must do the implementation. | `in-review` |
| — | `blocked` | The work cannot start. The issue body or a comment names the cause, for example `Blocked by: #12`. | `ready-for-agent` or `ready-for-human` |
| — | `in-review` | The code is complete. The code review or a by-hand check has not finished. | closed (completed) |
| `wontfix` | `wontfix` | We will not do this work. | closed (not planned) |
| — | `superseded` | A different issue or spec replaces this issue. A comment names it. | closed (not planned) |
| — | `spec` | The issue is a spec. Its tickets are sub-issues. | — |

When a skill mentions a role (for example "apply the AFK-ready triage label"), use the label string in the "Label in our tracker" column.

## Close an issue

- Done: remove the state label. Then run `gh issue close <n> --reason completed --comment "..."`.
- `wontfix` or `superseded`: keep the label. Then run `gh issue close <n> --reason "not planned" --comment "..."`.

## Rules

- Set `in-review` when the implementation is complete. Close the issue only after the review is complete. Do not close an issue while its review continues.
- A closed issue can keep one task box open. Name the open box in the closing comment, for example "The last box stays open: an analyst has not checked the page by hand yet."
- Wayfinding child tickets use assignees and the open/closed state. `issue-tracker.md` describes them.
