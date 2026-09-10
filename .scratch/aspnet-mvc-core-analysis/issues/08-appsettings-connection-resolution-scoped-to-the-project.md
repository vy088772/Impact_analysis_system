# 08 — Application settings connection resolution, scoped to the project

**What to build:** A Database Invocation in a Core System resolves to a Resolved Connection Source,
so its SP Catalog lookup reaches the right SQL Cache Identity. Today no Core
System resolves any connection, because resolution reads `Web.config` and no
Core System has one.

The lookup table is valid over one Project Connection Scope, never wider
(ADR-0018). One measured repository holds six projects in which the same key
name opens two different databases on two different servers; a repository-wide
table would give one of them an arbitrary win.

The resolver reads tolerantly — a byte-order mark and comments both occur in
real settings files — and sits beside the existing resolver rather than
replacing it (ADR-0008).

**Blocked by:** 01, 05.

**Status:** done

- [x] A named connection string in the base settings file resolves to a `{server, database}` pair.
- [x] A settings file carrying a byte-order mark parses.
- [x] A settings file carrying comments parses.
- [x] A database context type registered in the composition root against a named connection string resolves calls made on that context type.
- [x] A class holding two different context types resolves each call by the declared type of its receiver, not by the class.
- [x] A lookup table covers one project file directory, and a source file belongs to the nearest project file above it.
- [x] Two projects using one key name for two databases each resolve to their own database, with no merge and no ambiguity report.
- [x] A source file with no project file above it has no table, and its connections resolve to nothing with a stated reason.
- [x] A key read from the root configuration namespace rather than the connection strings section resolves to nothing and says so, because the two namespaces are not merged.
- [x] An environment-specific settings file that overrides a connection is reported as an observation and is not applied.
- [x] The existing `Web.config` resolution path is unchanged, verified against the WebForms system.

## Note

### Where the code is

Four new modules beside `webconfig_connection_resolver.py`, one reason to change per file:

- `code_analyzer/connection_string_value.py` — `ResolvedConnection` and the ADR-0008 synonym
  table. `Web.config` and `appsettings.json` are two file formats, but the connection-string
  *value* grammar is one, so it lives here once and both resolvers use it. It knows neither XML
  nor JSON, so adding a third settings format never touches it.
  `webconfig_connection_resolver` re-exports `ResolvedConnection`, so every existing import
  keeps working.
- `code_analyzer/appsettings_connection_resolver.py` — parses one Application Settings File
  into its `ConnectionStrings` lookup table plus the names in the Configuration Root Namespace.
- `code_analyzer/composition_root_reader.py` — reads `AddDbContext<T>(... GetConnectionString("Key") ...)`
  out of `Program.cs`/`Startup.cs`. It answers only "which context type is registered against
  which lookup key"; turning a key into `{server, database}` is the settings resolver's job.
- `code_analyzer/project_connection_scope.py` — `ProjectConnectionScope` (one project file
  directory's table) and `ProjectConnectionScopeIndex` (one table per project under a scan root).

`ProjectScanner` gains `connection_scopes` and a `_parse_csharp_file` that picks the table for
each source file before parsing it. `ProjectScanResult` gains `unresolved_connections` (per
file) and `connection_observations`.

### How the Web.config path stays unchanged

`ProjectConnectionScopeIndex` only acts when the scan root actually holds an `appsettings.json`.
A WebForms scan root holds none, so every lookup returns `None` and `ProjectScanner` uses the
`Web.config` table exactly as before. A repository holding both kinds also keeps both: a project
with a project file but no `appsettings.json` returns `None` too, and falls to the `Web.config`
path rather than to an empty Core table.

`DBConnectionTracker` tells the two apart by type (`isinstance(resolver, ProjectConnectionScope)`),
not by probing for an attribute. An attribute rename would otherwise send every Core project
silently back to the guessing this ticket exists to remove.

### Three things beyond the bullet list

**1. The `DbContext` type-name guess is gone.** `_extract_mvc_connections` used to turn
`TOPCSCYContext` into database `TOPCSCY` by stripping `Context` and `Db` from the type name.
That is the same family of shortcut as the `<appSettings>` key-as-database-name rule ADR-0008
says "must be replaced, **not extended**" — a context type's name and the database it opens are
routinely different. A context type the composition root never registered now resolves to
nothing and reports `context_type_not_registered`, and `_report_unregistered_context_types`
makes that gap visible rather than silent. Ambient `*Context` types ASP.NET declares itself
(`HttpContext`, `ControllerContext`, …) are excluded, because reporting them would drown the
real gaps.

*Amended while working ticket 09.* Once ETR became scannable, the five measured repositories
could be counted for the first time, and this rule reported twenty-four times — every one of
them a framework type, none of them true. Six names joined the exclusion list:
`ActionExecutingContext`, `ActionExecutedContext`, `AuthorizationFilterContext`,
`ClientModelValidationContext`, `TagHelperContext` (ASP.NET Core MVC) and `PrincipalContext`
(`System.DirectoryServices.AccountManagement` — a directory, not a database). Measured after:
zero reports across all five, and every database context type the repositories declare is
registered, so nothing true was lost.

A name list is the wrong shape for this and will miss the seventh framework type the next
repository brings. The evidence-based rule — report only a type the source declares as a
database context — is available (`class X : DbContext`), but it goes silent on a context
declared in a referenced project, so it is a decision for its own ticket, not a quiet swap.

**2. A root-namespace read is only reported when it names a connection.** Criterion 9 is
implemented for the reads it is about. Code reads the Configuration Root Namespace mostly for
log levels and feature flags; recording every `_configuration["LogLevel"]` as an unresolved
connection would bury the real gaps. So the reason is recorded when the key names an entry in
the `ConnectionStrings` section, or when its own root value parses as a connection string —
which is exactly the shape criterion 9 names. `Configuration["ConnectionStrings:Key"]` carries
the section prefix and resolves normally.

**3. Trailing commas parse too.** The ticket names a byte-order mark and comments. A trailing
comma arrives with them — commenting one connection out of a block leaves one behind — and
.NET's own configuration reader accepts it, so refusing it would fail a real file for no gain.

### Reasons a connection reports

`unresolved_connections` entries carry one of: `no_project_connection_scope`,
`connection_key_not_in_project_scope`, `root_configuration_namespace_not_connection_strings`,
`context_type_not_registered`.

### Deliberately not done here

The environment override is recorded on `ProjectScanResult.connection_observations` and merged
across scan roots, but no `/refresh` or `/analyze` response prints it yet. Surfacing the numbers
and the reasons is ticket 16's coverage report; this ticket produces the evidence it will read.

### Verification

New tests: `tests/test_appsettings_connection_resolution.py` (16 tests — the sixteenth arrived with ticket 09's amendment above) — one per acceptance
criterion, plus the unregistered-context, non-connection-root-read, section-indexer cases, and
an end-to-end `ProjectScanner` scan that asserts both `connection_sources` and
`unresolved_connections`.

`tests/test_program_refresh.py`: the three hand-built `ProjectScanner` doubles gained
`connection_resolver`/`connection_scopes`, and their fake trackers gained `unresolved`, because
the real collaborator now has them.

Scan cache version 29 → 30: a cached Core scan's `connection_sources` holds the old guessed
values, which are not the new resolved ones.

Full suite before this change: 13 failed, 718 passed, 1 skipped. After: 12 failed, 734 passed,
1 skipped. Every one of the 12 is in the pre-existing 13 (Windows CRLF line endings, a
temp-path assertion, wrapper-contract state, and the out-of-scope uncommitted `Web.config`
edits in the Y-DOCs clone); the thirteenth,
`test_contract_transaction.py::test_deterministic_transaction_identity_for_equivalent_staged_content`,
is order-dependent and passed this run. None touch this ticket's files.
