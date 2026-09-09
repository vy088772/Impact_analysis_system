# WebForms Package Restore

Status: ready-for-agent

## Problem Statement

The Y-DOCs WebForms System runs its analysis without a semantic model, and has
been doing so silently in the sense that nobody looked. A baseline captured on
2026-09-09 shows it:

```
sp_relations       637
table_relations    392
wrapper_calls     6402
  evidence_proven                214   (3.3%)
  evidence_unresolved           5839  (91.2%)
  semantic_binding_resolved       14

Semantic Binding Availability, per scan root
  TTPUR          unavailable_reference_resolution_failed   31 unresolved
  ATV            unavailable_reference_resolution_failed    1 unresolved
  Notification   unavailable_reference_resolution_failed    1 unresolved
  Response       unavailable_reference_resolution_failed    1 unresolved
  TaskSchedule   available                                  0
```

Four of five scan roots have no semantic model, and 14 of 6402 wrapper calls
resolve a receiver through one. Two separate causes produce that:

- **TTPUR** names 31 unresolved references. All 31 are NuGet package assemblies
  declared in the old-style form, pointing at a packages directory that holds
  one of the 24 packages its `packages.config` lists. The rest were never
  restored into the clone.
- **ATV, Notification and Response** each name exactly one unresolved
  reference: a project reference to TTPUR.

TTPUR holds 541 of the system's 588 C# files and 247 of its 259 pages. It is the
one that matters, and its cause is the restorable one.

The analyzer is not lying here. It reports `unavailable_reference_resolution_failed`
exactly as ADR-0021's principle requires. The gap is real, visible, and
unaddressed.

## Solution

Restore an old-style project's declared packages before building its
compilation, the same way the MVC/Core work restores an SDK-style project's
package references. A project that declares packages and cannot restore them
reports unavailable and names the cause, as it does now.

## User Stories

1. As a maintainer, I want an old-style project's declared packages restored before compilation, so that a reference pointing into the packages directory resolves.
2. As a maintainer, I want the dominant WebForms scan root to report Semantic Binding Availability as available, so that wrapper receiver resolution has a semantic model to ask.
3. As a maintainer, I want a project whose restore fails to report unavailable and name the cause, so that a failure stays visible rather than becoming an empty compilation.
4. As a maintainer, I want a project that declares no packages to behave exactly as it does today, so that the change cannot disturb a project it does not apply to.
5. As a reviewer, I want this System's own baseline captured before the change and compared after, so that a changed number can be classified as a repair or a regression.
6. As a reviewer, I want this work kept out of the MVC/Core change set, so that neither effort's baseline is contaminated by the other's improvements.

## Implementation Decisions

- Package restore for old-style projects reads the project's declared package
  list and restores into the directory the reference hint paths point at.
- Restore runs once per project, and is skipped when the referenced assemblies
  already resolve.
- A project whose restore fails reports
  `unavailable_reference_resolution_failed` and names the cause. It never
  reports available.
- Recursive project reference compilation is not part of this ticket. It is
  what blocks the three small scan roots, and resolving it before TTPUR
  compiles would change nothing.

## Testing Decisions

The seam is `StaticAnalyzerHost`, matching the prior art in
`test_semantic_binding_availability.py`: write a minimal old-style project into
a temporary directory, run the host, assert on the reported availability and the
named unresolved references.

One end-to-end smoke test runs against the real cloned WebForms system and
asserts that its dominant scan root reports available.

## Out of Scope

- **Recursive project reference compilation.** It gates three scan roots holding
  43 of 588 C# files. It is worth its own ticket after this one.
- **Everything in the ASP.NET MVC / Core Analysis effort.** The two are kept
  apart deliberately, so each has a clean baseline.
- **The uncommitted Web.config edits in the Y-DOCs clone.** Two local edits
  currently change which connections resolve for this System, which means its
  analysis is not reproducible from a fresh clone. That is a third ticket.

## Further Notes

This work was found by capturing the WebForms baseline that the MVC/Core effort
needed as a regression guard. The baseline's purpose was to detect damage; it
found a pre-existing gap instead.

Keeping the two efforts apart is the point. If this restore landed inside the
MVC/Core change set, the WebForms numbers would rise sharply, and no later
comparison could tell which rise came from which change.
