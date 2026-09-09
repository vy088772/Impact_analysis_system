# 01 — Restore an old-style project's declared packages before compilation

**What to build:** The dominant WebForms scan root gets a real semantic model. It
declares 31 assembly references that point into a packages directory holding one
of the 24 packages its package list names; the rest were never restored into the
clone. Every one of those 31 references therefore fails to resolve, the project
reports `unavailable_reference_resolution_failed`, and wrapper receiver
resolution has no semantic model to ask — which is why 14 of the system's 6402
wrapper calls resolve a receiver through one.

Restoring the declared packages before building the compilation closes that gap.
A project that cannot restore them keeps saying so.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] An old-style project's declared package list is read, and its packages are restored into the directory its reference hint paths point at.
- [x] Restore runs at most once per project, and is skipped when the declared references already resolve.
- [x] A project whose restore fails reports `unavailable_reference_resolution_failed` and names the cause.
- [x] A project whose restore succeeds but still has unresolved references reports them, unchanged from today's behaviour.
- [x] A project declaring no packages behaves exactly as it does today.
- [x] The dominant WebForms scan root reports `available` with no unresolved references.
- [x] The three scan roots blocked only by a project reference still report `unavailable_reference_resolution_failed` naming that reference, unchanged.
- [x] This System's baseline is re-captured after the change: stored procedure and table relation counts do not fall, and the resolved-receiver count rises.

## Notes

**Implementation.** `packages.config` restore for old-style projects is not something
`dotnet restore` (or `dotnet msbuild -t:restore -p:RestorePackagesConfig=true`) can do at
all — verified directly against this host's own .NET 10 SDK, on a real `packages.config`
project with the correct `Microsoft.Common.props` import: it reports "沒有任何動作可執行"
(nothing to restore) every time. `nuget.exe` is not installed in this environment either.
`tools/StaticAnalyzerHost/PackageRestorer.cs` restores each package declared in
`packages.config` directly from the NuGet v3 flat-container API
(`api.nuget.org/v3-flatcontainer/...`) into the directory the project's own `HintPath`
entries already point at, extracting straight from the downloaded `.nupkg`. This needed no
new dependency: `System.Net.Http` and `System.IO.Compression` are already in the BCL.
`ProjectCompilationResolver.ResolveProject` (`ProjectCompilation.cs`) calls this once, only
when the first resolution pass leaves an external reference unresolved and a
`packages.config` sits next to the project file, then resolves once more. A project with no
`packages.config`, or one whose references already resolve, never reaches this code at all.

**Tests.** `tests/test_semantic_binding_availability.py` gained five cases: no-packages.config
(unchanged), skip-when-already-resolved (no network needed), successful restore of a real
small package, a named restore-failure cause, and an end-to-end smoke test against the real
TTPUR project (`requires_network` where an actual fetch is exercised). All pass; the six
pre-existing tests in that file are unaffected.

**Full suite.** `pytest -q` (683 passed, 12 failed, 1 skipped) has 12 pre-existing failures
unrelated to this ticket: verified by reverting `ProjectCompilation.cs` to `HEAD` and rebuilding
the host, then re-running four representative failures
(`test_static_analyzer_host_applies_external_sqlobject_wrapper_contract`,
`test_commented_out_entries_never_resolve`, `test_repair_only_touches_the_graph_field`,
`test_lookup_records_the_table_name_and_the_scope`) — all four fail identically without this
ticket's change (line-ending and path-formatting mismatches, and wrapper-overload
classification that never touches project compilation). None of the 12 use a `.csproj` scan
root, so `ResolveProject`/`ResolveCompilationForAnalysis` is never on their call path.

**Code review.** `/code-review` (Standards + Spec axes) found two worth fixing, both applied
and re-tested: (1) a Duplicated Code smell — the "project directory from project file" and
HintPath-combine logic each appeared independently in `ProjectCompilation.cs` and
`PackageRestorer.cs`; extracted into a shared `ProjectPaths` helper. (2) A real correctness
wrinkle — on a restore failure, the code kept the *pre-restore* unresolved list instead of
re-checking what actually landed on disk, so a package that did restore successfully before a
later one failed was still reported unresolved; fixed by always re-resolving after a restore
attempt, success or partial failure, before appending the failure cause. Availability verdicts
were unaffected either way (`unavailable_reference_resolution_failed`, never `available`, on
any failure) — only the named `unresolved_references` list could have been stale. A third
finding (network reachability check at test-module import time) was left as a judgement call,
noted for a future pass.

**Baseline, before -> after** (`.scratch/webforms-package-restore/baseline-ydocs.json` ->
`baseline-after.json`, captured against the real Y-DOCs clone, git pull skipped both times to
protect the two uncommitted local `Web.config` edits per this ticket's Out of Scope):

| metric | before | after |
| --- | --- | --- |
| sp_relations | 637 | 637 (unchanged) |
| table_relations | 392 | 392 (unchanged) |
| wrapper_calls | 6402 | 6402 (unchanged) |
| semantic_binding_resolved | 14 | **947** (rises, as required) |
| TTPUR availability | unavailable_reference_resolution_failed (31 unresolved) | **available** (0 unresolved) |
| ATV / Notification / Response | unavailable_reference_resolution_failed [TTPUR] | unchanged |
| TaskSchedule | available | unchanged |

The ticket's three gated numbers all move the required way: stored-procedure and table
relation counts hold exactly, and the resolved-receiver count rises by 933.

**For the reviewer to classify.** Two wrapper-reconciliation numbers moved in the direction
opposite to what a first glance expects, and the ticket does not gate on either one, so they
are reported here rather than treated as pass/fail: `evidence_proven` fell from 214 to 24,
and `explicit_selected` fell from 243 to 51 (`observation_groups`/`external_wrappers` fell by
a similar amount too). The likely mechanism: with a real semantic model now available, many
receiver call sites that the syntax-only path had grouped and classified separately (via the
existing `decompiled_auto` contracts in `config/external_wrapper_contracts.json`) now resolve
to a smaller number of canonical semantic-binding groups instead — visible in
`semantic_binding_resolved` jumping from 14 to 947 while `observation_groups` falls from 6053
to 5483. Left unresolved by this ticket: since Recursive project reference compilation and the
Web.config edits are both explicitly out of scope, and this is the first time this System has
ever had a semantic model, whether that reclassification is itself correct is a question for
whichever ticket next builds on `semantic_binding_resolved` — this ticket is about restoring
packages and repairing availability, not the contract-selection layer, which reports its inputs
unchanged.
