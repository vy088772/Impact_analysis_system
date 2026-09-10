# ASP.NET MVC / Core Analysis

Status: ready-for-agent

## Problem Statement

The analyzer answers impact questions for ASP.NET WebForms Systems. It answers
almost nothing for the ASP.NET MVC and ASP.NET Core Systems in the same
catalog, and it does not say that it failed.

Five real MVC/Core repositories were measured. Every one of them breaks a
different assumption the WebForms path was built on:

```
IQCS          1 project    net6.0   262 wrapper calls, 261 pass the SP name in a variable
RTTalentDB    3 projects   net8.0   50 of 56 controllers use C# 12 primary constructors
ETR           1 project    net6.0   70 raw ADO.NET calls; one controller serves three screens
EnterpriseApp 6 projects   net8.0   one connection key names two different databases
TOPCSCY       1 project    net6.0   13 Areas, 510 views
```

Four failures compound:

1. **No semantic model.** Every Core project uses an SDK-style project file.
   The project reader understands only the old-style form, so it finds zero
   source files and zero references — and then reports Semantic Binding
   Availability as `available`. An empty compilation currently looks like a
   successful analysis.
2. **No procedure names.** Wrapper command text resolves only from a string
   literal at the call site. IQCS resolves 1 name out of 262.
3. **No Resolved Connection Source.** Connection resolution reads `Web.config`
   only. No Core System has one, so every Database Invocation in all five
   repositories resolves to no `{server, database}`, and therefore reaches no
   SP Catalog.
4. **No program identity.** A program code resolves to files by base name.
   In MVC that name may sit on the view file, on the view folder, or on
   neither, and one controller may serve several screens.

The result is not a wrong answer. It is an empty one that looks authoritative,
which is the failure mode this codebase exists to prevent.

## Solution

Bring MVC and Core Systems to the same three layers the WebForms path already
delivers: the impact chain, the displayed fields, and the UI anchors.

The unit of analysis becomes the **Program Screen** — one View file plus the
actions that serve it (ADR-0019). A **View Anchor** carries the screen-to-action
edge that a WebForms control event carries today. A **Project Connection Scope**
bounds each connection lookup table to one project file (ADR-0018), because one
key name can open two databases inside a single repository. The **Framework
Label** stops deciding which parsers mount and becomes a reported fact
(ADR-0021), so a repository holding both WebForms and MVC loses neither.

Underneath, three analyzer gaps close: the project reader learns the SDK-style
form and reports honestly when it cannot build a compilation; wrapper receiver
resolution walks the inheritance chain to the type that declares the method;
and wrapper command text reuses the existing same-method identifier tracer
(ADR-0020).

## User Stories

### The impact chain

1. As an analyst, I want to ask which stored procedures a Core program touches, so that I get the same answer quality I already get for a WebForms program.
2. As an analyst, I want a Database Invocation whose command text arrives in a local variable to resolve its Executed Procedure Name, so that a system written in the common local-variable style is not reported as empty.
3. As an analyst, I want a Database Invocation whose command text arrives as a method parameter to stay unresolved with a reason code, so that an unproven name is never presented as a proven one.
4. As an analyst, I want a Database Invocation to resolve its Resolved Connection Source from the application settings file, so that its SP Catalog lookup reaches the right SQL Cache Identity.
5. As an analyst, I want a raw ADO.NET call whose connection string comes from a controller field to resolve the same way as one that comes from an injected context, so that ETR-shaped and IQCS-shaped systems both answer.
6. As an analyst, I want a Database Invocation through an inherited wrapper method to bind to a Contract, so that a local context deriving from an external base class is not treated as an unknown receiver.
7. As an analyst, I want an Uncataloged Database found in a Core System to be reported exactly as it is for a WebForms System, so that the catalog gap surfaces through the path that already exists for it.

### The program

8. As an analyst, I want a specification program code to resolve to a Program Screen, so that the answer covers one screen rather than a whole controller.
9. As an analyst, I want a program code that names a view folder to resolve, so that IQCS-shaped naming works.
10. As an analyst, I want a program code that names a view file to resolve, so that RTTalentDB-shaped naming works.
11. As an analyst, I want a program code inside an Area to resolve, so that thirteen Areas holding same-named views do not collide.
12. As an analyst, I want a controller that serves three screens to yield three Program Screens, so that one screen's stored procedures are not reported under another screen's name.
13. As an analyst, I want a program code that matches nothing to be reported as not found, so that a silent empty result never passes for an answer.
14. As a reviewer, I want a program code to never match a longer name that merely contains it, so that a shorter program name never absorbs a longer one.

### The UI layers

15. As an analyst, I want the fields a Core screen displays, so that I can ask which screens show a column.
16. As an analyst, I want a field label written as plain markup text to be extracted, so that ETR-shaped and IQCS-shaped views answer directly.
17. As an analyst, I want a field label that resolves through a display attribute to a resource file to be extracted, so that a view containing no readable label still answers.
18. As an analyst, I want a display attribute carrying a literal label to be extracted without a resource lookup, so that both attribute shapes work.
19. As an analyst, I want a markup-layer View Anchor to be reported as determined, so that a form's action is proven, not guessed.
20. As an analyst, I want a controller-and-action shaped URL inside the view's own script block to be reported as a candidate at `likely`, so that an AJAX-only endpoint is not silently lost.
21. As an analyst, I want determined and candidate View Anchors kept apart in the result, so that a guess never reads as proof.
22. As an analyst, I want a ViewComponent a screen renders to contribute its stored procedures, so that the MVC path is not shallower than the WebForms user-control path.
23. As an analyst, I want a ViewComponent's contribution labelled as coming from a shared component, so that a menu component's tables do not drown the screen's own.
24. As an analyst, I want a partial view to contribute the same way a ViewComponent does, so that the two shared-markup mechanisms behave alike.
25. As an analyst, I want a Razor Pages screen to anchor through its page model, so that a Core System built on Razor Pages is covered.
26. As a reviewer, I want a view carrying a page model file but no page directive to be treated as MVC, so that an auto-generated empty page model creates no false anchor.

### Honesty and reporting

27. As a maintainer, I want the refresh command to print the Framework Label and the parsers that mounted, so that I can see what the scanner decided.
28. As a maintainer, I want a scan root whose framework cannot be identified to fail, so that a C#-only fallback never passes for a full scan.
29. As a maintainer, I want a scan root holding both WebForms and MVC files to parse both, so that a mixed repository loses neither side.
30. As a maintainer, I want a Core project with no resolvable references to report Semantic Binding Availability as unavailable, so that an empty compilation never reports `available`.
31. As a maintainer, I want each unresolved Database Invocation to name its reason, so that a coverage number can be acted on rather than merely observed.
32. As a maintainer, I want a connection lookup key that names no entry in its Project Connection Scope to resolve to nothing, so that a real configuration defect in the analyzed system stays visible.
33. As a maintainer, I want an environment-specific settings file that overrides a connection to be reported, so that a per-environment database difference is visible without being silently applied.

### Regression safety

34. As a reviewer, I want the WebForms baseline captured before any change, so that a changed number can be classified as a repair or a regression.
35. As a reviewer, I want WebForms stored-procedure counts to rise and never fall, so that a shared code path change cannot quietly remove evidence.
36. As a reviewer, I want a repository written before this change to scan exactly as it does now where no new rule applies, so that the change cannot re-rate existing evidence by accident.

## Implementation Decisions

### Framework detection and parser mounting

- `ProjectTypeDetector` keeps detecting, but its parser list no longer gates.
  `ProjectScanner` mounts parsers by the union of file extensions actually
  present under the scan root. A root holding both WebForms and Razor views
  mounts both parsers (ADR-0021).
- The Framework Label travels from the scan into the refresh response, per scan
  root, alongside the parsers that mounted. The refresh command prints both.
- A scan root detected as unknown raises rather than falling back to a C#-only
  scan.

### Project compilation

- The project reader gains the SDK-style form: implicit source globbing with
  removal items honoured, and package reference resolution.
- Package references resolve through the project's restore assets file. When
  none exists, the refresh runs a restore once for that project. When no .NET
  SDK is present, or restore fails, the project reports
  `unavailable_reference_resolution_failed`.
- An SDK-style project that yields no source files reports
  `unavailable_reference_resolution_failed`, never `available`. This is a bug
  fix that lands regardless of the rest of the ticket.
- A project reference stays unresolved. The referencing project reports
  `unavailable_reference_resolution_failed` and is analyzed syntactically.
- Old-style project handling is unchanged.

### Wrapper resolution

- Wrapper receiver type resolution walks the inheritance chain to the type that
  declares the invoked method, and keys the Contract on that declaring type.
  This requires the semantic model, so it depends on the project compilation
  work above.
- Wrapper command text resolution reuses the existing same-method identifier
  tracer, which already walks an identifier back to declarations and
  assignments preceding the call inside the same method. It is wired to the
  wrapper path (ADR-0020).
- Command text arriving as a method parameter stays unresolved and carries its
  own reason code. No interprocedural propagation.
- Contract identity is untouched. The three repositories carrying the same
  external library ship three different assembly revisions, and the existing
  Assembly Revision Boundary already separates them.

### Connection resolution

- A new resolver reads the application settings file and produces Resolved
  Connection Sources. It parses tolerantly: a byte-order mark and comments both
  occur in real files.
- It sits beside the `Web.config` resolver rather than replacing it. The two
  are never merged, following ADR-0008.
- A lookup table is valid over one Project Connection Scope. A source file
  belongs to the nearest project file above it. Tables are never merged across
  projects (ADR-0018).
- Two lookup shapes resolve: a context type registered in the composition root
  against a named connection string, and a named connection string read
  directly into a field later used to open a connection. The receiver's
  declared type selects among several registered contexts.
- A key read from the root configuration namespace rather than the connection
  strings section resolves to nothing, and says so. The two namespaces are not
  merged.
- Only the base settings file supplies connections. An environment-specific
  file overriding a connection is recorded as an observation and reported, not
  applied.
- Server normalization gains two rules: strip a protocol prefix, and strip a
  port suffix. Existing rules are unchanged. This is a repair of the existing
  function and benefits WebForms equally.

### Program Screen resolution

- Program code resolution tries three entry points, in order: a view folder
  whose name matches, a view file whose base name matches (an optional `View`
  suffix allowed), and a controller file whose name matches. Area-qualified
  paths are searched the same way.
- A match requires the whole name, never a substring.
- The resolved Program Screen holds one view plus its serving actions: actions
  whose name equals the view name, and actions named by the view's View
  Anchors.
- The controller is a traversal path, not the scope. A controller may appear in
  several Program Screens.
- The existing base-name program matching stays in place for WebForms and is
  not routed through the new resolution.

### View analysis

- The Razor parser produces the same structured result shape the ASPX parser
  produces, so that the view-layer summary, the flow chain builder, and the
  snippet extractor consume both without branching.
- Displayed field text resolves from three sources: plain markup text in table
  headers and labels, the model property named by a model-bound attribute, and
  a display attribute resolved either to its literal label or through a
  resource file entry.
- View Anchors are extracted at two strengths, carried separately: markup-layer
  attributes and form actions are determined; a controller-and-action shaped
  URL inside the view's own script block is a candidate rated `likely`.
- A view is treated as Razor Pages only when it carries a page directive. A
  page model file alone is not sufficient.
- ViewComponent and partial view references extend the chain, and their
  contribution is labelled as coming from a shared component.
- The scan cache version increments, because the stored view records change
  shape.

## Testing Decisions

A good test here states an externally observable fact and nothing about how the
code reaches it. It asserts on what the analysis reports — a resolved procedure
name, a `{server, database}` pair, an availability state, a Program Screen's
file set, an anchor's strength — never on intermediate structures. Every test
that asserts an absence also asserts the reason given for it, because this
codebase's failure mode is a silent empty result, not a crash.

### Seams

Two existing seams, no new ones.

- **`analyze_service`** (its analyze and refresh entry points) is the
  Python-side seam. Program Screen resolution, View Anchors, displayed fields,
  connection resolution results, the Framework Label, and the refresh summary
  are all observable here. `ProjectScanner`, the flow chain builder, the Razor
  parser and the connection resolvers are exercised through it, not directly.
- **`StaticAnalyzerHost`** is the C#-side seam. Project compilation, Semantic
  Binding Availability, receiver inheritance resolution and wrapper command
  text are observable here. The two runtimes cannot share one seam.

### Prior art

- `test_execution_path_integration.py` and `test_program_refresh.py` show the
  `analyze_service` pattern: build a scan result, patch the store, drive the
  request, assert on the response.
- `test_semantic_binding_availability.py` shows the `StaticAnalyzerHost`
  pattern: write a minimal project into a temporary directory, run the host,
  assert on the reported availability and the named unresolved references. It
  also shows the one end-to-end smoke test against a real cloned project, which
  this ticket copies for each measured repository shape.
- `test_connection_tracking.py` shows the connection resolver pattern and the
  two-namespace separation this ticket extends.

### Fixtures

Minimal projects written into temporary directories, following house practice —
there is no fixtures directory. One project per measured shape: SDK-style with
package references, SDK-style with an unresolvable project reference, a
primary-constructor service, a same-method variable command text, a
method-parameter command text, a repository holding two projects that use one
connection key for two databases, an Area-qualified view, a view whose labels
resolve through a resource file, and a view carrying a page model but no page
directive.

### Cleanup

`test_mvc_project_scan.py`, `test_mvc_parsing.py` and `test_multi_parser.py`
contain zero assertions and are print-only scripts; one hard-codes an absolute
path to a developer machine. They pass today while verifying nothing. They are
replaced by the tests above rather than left beside them.

### Baseline

The Y-DOCs WebForms baseline is captured before the first change and compared
after each slice. Stored procedure and table relation counts may rise, because
the command text and server normalization changes are shared with the WebForms
path. They may not fall.

## Out of Scope

- **Interprocedural command text propagation.** Seventeen calls across two
  measured repositories pass a command text across a method boundary. They stay
  unresolved with a reason code (ADR-0020).
- **Recursive project reference compilation.** Three Y-DOCs scan roots are
  blocked by exactly this: each names an unresolved project reference to the
  TTPUR project and therefore gets no semantic model. They are deferred anyway,
  because those three roots hold 43 of the system's 588 C# files, and TTPUR —
  which holds the rest — is blocked by a different cause. Resolving the
  recursion without first resolving that cause would change nothing. The claim
  that no measured repository needs it was wrong and is corrected here.
- **Cross-project calls over HTTP.** The one repository holding both a web
  application and an API shows no HTTP client use in the web application.
- **Blazor.** No measured repository contains a Blazor component.
- **Vue.** The existing Vue parser is untouched.
- **Applying environment-specific settings.** Overrides are reported, never
  applied.
- **Registering the measured repositories in the catalog.** Which repositories
  become Systems is a separate decision.
- **The uncommitted Web.config edits in the Y-DOCs clone.** Two local edits
  currently change which connections resolve for that System. That is a real
  problem and belongs to its own ticket.

## Further Notes

The five repositories are the specification for this ticket in a way prose
cannot replace. Each one falsified a rule that looked correct against the
others:

- IQCS falsified "the SP name is a literal at the call site".
- RTTalentDB falsified "the program name prefixes the controller name", and
  showed that a service's injected context may be a primary constructor
  parameter rather than a field.
- ETR falsified "one controller is one screen", and showed a controller that
  injects no service and opens its own connection.
- EnterpriseApp falsified "one repository has one connection lookup table".
- TOPCSCY falsified "views live directly under a single views root".

Two earlier proposals for program resolution were tried against this evidence
and withdrawn, which is why ADR-0019 records the reasoning rather than only the
rule.

Acceptance is measured, not sampled. For each repository, two ratios are
reported: Database Invocations that resolve an Executed Procedure Name, and
Database Invocations that resolve a Resolved Connection Source. Both start from
a known baseline — IQCS resolves 1 of 262 names and 0 of 262 connections today.
Every invocation below the line must name its reason, because a ratio alone
cannot distinguish a resolution that improved from one that merely became
confident.
