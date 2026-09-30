# 04 — The project scanner and the connection tracker resolve through the Connection Lookup

**What to build:** The project scanner makes one Connection Lookup for its
scan root. It gives the connection tracker the view of each source file. The
tracker does not select a table by its type. The project-scope index and the
scan root table of the project scanner go away. A `Web.config` table now
covers one Project Connection Scope. The scan output of the 10 local scan
roots does not change. This ticket is the second half of step 1 of the spec.
See the spec, sections "Delivery order", "Connection Lookup", "Documentation",
and "Testing Decisions".

**Blocked by:** 02 — One module reads, remaps, and builds a connection source
entry; 03 — The Connection Lookup answers which connection a lookup key opens
for one source file

**Status:** done (2026-09-30)

- [x] Before the change, scan the 10 local scan roots with the project scanner
      directly. Keep the connection sources and the unresolved connections of
      each scan as the baseline.
- [x] The project scanner holds one Connection Lookup. It gives the tracker
      the view of the file that the tracker reads. The tracker parameter for
      the view has the name `connections`.
- [x] The tracker asks the view for each lookup key. It does not select a
      table by its type. It has no branch for the guess from an empty table.
- [x] On the `Web.config` path, a `GetConnectionString` read always uses the
      lookup key as the Database name. The tracker reads the fact of the view
      for this rule.
- [x] The tracker records the reason for an untraced Field-Held Connection
      only on the Application Settings File path. The tracker reads the fact
      of the view for this rule.
- [x] A tracker with no view keeps the key-as-name guess.
- [x] The project-scope index goes away. The scan root table of the project
      scanner and its loader go away.
- [x] The project scanner no longer uses the file search of the legacy
      configuration parser.
- [x] The command-line database detection keeps the legacy configuration
      parser and still works.
- [x] The project scanner builds each stored entry with the builder of ticket
      02. It does not write the declaring file to the C# Scan Result.
- [x] The project scanner reports each Environment Settings Override through
      the Connection Lookup.
- [x] The scan cache version does not rise.
- [x] The tracker tests give the tracker a view that the Connection Lookup
      makes from files. The scanner test stubs set one attribute.
- [x] ADR-0018 gains an amendment. It states that a `Web.config` table also
      covers one Project Connection Scope. It states the scan root
      `Web.config` rule for a project with no configuration file.
- [x] The Project Connection Scope entry of the glossary agrees with the
      amendment. The glossary gains no term for the Connection Lookup.
- [x] After the change, scan the 10 local scan roots again. The connection
      sources and the unresolved connections are the same as the baseline.
      Record the result in this ticket under a `## Comments` heading.
- [x] All tests pass. Take the test baseline in the same directory as the
      change, because the results of three tests depend on the path.

## Comments

### 2026-09-30 — the scan comparison (acceptance of step 1)

- The comparison scanned the 10 local scan roots with the project scanner
  directly: `ProjectScanner(project_root).scan_project(analyze_sp=False)`. It
  did not use the scan cache.
- The 10 scan roots are the roots of the local scan cache: IQCS, RTTalentDB,
  STC, TOPCSCY, and the Y-DOCs directories ATV, Notification, Response,
  TTPUR, TTRDQ, and TaskSchedule.
- Each scan wrote three values to one JSON file: the connection sources, the
  unresolved connections, and the connection observations.
- Result: the JSON file of each scan root is the same, byte for byte, before
  the change and after the change. A third scan, after the corrections of the
  code review, gave the same files.
- The counts of the baseline:

  | Scan root | Files | Connection sources | Unresolved connections |
  | --- | --- | --- | --- |
  | IQCS | 267 | 106 | 96 |
  | RTTalentDB | 381 | 57 | 70 |
  | STC | 24 | 12 | 0 |
  | TOPCSCY | 714 | 319 | 242 |
  | Y-DOCs/ATV | 16 | 3 | 0 |
  | Y-DOCs/Notification | 4 | 1 | 0 |
  | Y-DOCs/Response | 20 | 8 | 0 |
  | Y-DOCs/TTPUR | 539 | 263 | 0 |
  | Y-DOCs/TTRDQ | 280 | 34 | 0 |
  | Y-DOCs/TaskSchedule | 3 | 2 | 0 |

- No scan root has an Environment Settings Override, so the connection
  observations are empty in each scan.

### 2026-09-30 — implementation notes

- Files that this ticket changed:
  - `code_analyzer/db_connection_tracker.py`
  - `code_analyzer/project_scanner.py`
  - `code_analyzer/project_connection_scope.py`
  - `code_analyzer/connection_lookup.py`
  - `tests/test_connection_tracking.py`
  - `tests/test_appsettings_connection_resolution.py`
  - `tests/test_connection_field_resolution.py`
  - `tests/test_program_refresh.py`, `tests/test_inline_sql_regex_fallback.py`,
    and `tests/test_inline_sql_table_relations.py` (the scanner stubs and
    their imports only)
  - `docs/adr/0018-connection-lookup-tables-are-scoped-to-the-project-file.md`
  - `CONTEXT.md` (the Project Connection Scope entry only)
- The tracker parameter is `connections`. The tracker keeps the view in the
  attribute `file_connections`, because the attribute `connections` already
  holds the result of the tracker. The project scanner sets
  `file_connections` before it reads each file.
- A tracker with no view uses `FileConnections()`. That view has no table, so
  it gives the key-as-name guess. The tracker has no branch for the guess.
- The project scanner holds the Connection Lookup in the attribute
  `connection_lookup`. A scanner test stub sets this one attribute.
- The three namespace constants of the tracker take their values from the
  Connection Lookup module.
- `ProjectConnectionScopeIndex` is gone. `ProjectConnectionScope` lost the
  fields `app_settings` and `unresolved_reason` and its truth-value method.
  Only the tracker and the index used them.
- The search for an Application Settings File below the scan root is now in
  the Connection Lookup. The list of ignored directories stays in
  `project_connection_scope.py` with the public name
  `IGNORED_DIRECTORY_NAMES`, because the search for a composition root uses
  the same list.
- The project scanner keeps its import of the legacy configuration parser for
  `detect_databases_from_config` only.
- `db_connection_tracker.py`, `project_scanner.py`,
  `tests/test_connection_tracking.py`, and `tests/test_program_refresh.py` use
  CRLF line ends. Keep CRLF when a script writes them.
- Test result in this directory. Before: 16 failed, 1351 passed, 2 collection
  errors. After: 16 failed, 1361 passed, 2 collection errors. The list of
  failures is the same. One of the new tests is from this ticket. The others
  are from parallel sessions.
- The type check of the tracker, the Connection Lookup, and
  `project_connection_scope.py` gives no error.

### 2026-09-30 — one difference from the spec

- The spec says that two tracker rules read the fact
  `reads_application_settings_file`. The tracker reads it in four places.
- The two rules of the spec are the `GetConnectionString` rule and the reason
  for an untraced Field-Held Connection.
- The other two reads are at the start of the search for a Context Connection
  Registration and at the start of the search for a read of the Configuration
  Root Namespace. Before this ticket, these two searches did not run on the
  `Web.config` path.
- Without the first of these reads, the `Web.config` path records
  `receiver_declaration_unresolved`. The tracker writes that reason itself and
  does not ask the view.
- Without the second, a read of `Configuration["ConnectionStrings:Key"]`
  resolves through the `Web.config` table.
- Each of the two results changes the scan output, and step 1 must change no
  scan output. The code review confirmed this reasoning. The old tracker had
  the same four tests.

### 2026-09-30 — notes for ticket 05

- The tracker reads only the Database and the server of an answer. It does
  not keep the declaring file. `ConnectionInfo` has no field for it. Ticket 05
  adds the field and gives it to `resolved_entry`.
- `analyze_related_files` in the project scanner calls the C# parser directly.
  It now sets the view of each file before the call. Before this ticket, that
  command-line path used the table of the last scanned file. The service scan
  does not use this path, and no test covers it.
- The new scanner test
  `test_project_scanner_gives_two_web_applications_under_one_scan_root_their_own_table`
  checks that a stored entry holds only `database` and `server`. Ticket 05
  must change that check when it writes `declared_in`.
- The three results of ticket 03 that differ from the old structures now apply
  to the scan. No local scan root has those layouts.

### 2026-09-30 — code review

- The code review had two axes (Standards and Spec). The Spec axis found no
  missing requirement and no difference between the old tracker and the new
  tracker.
- Changes after the review: the description of `project_connection_scope.py`
  no longer says that a table never widens to the scan root, the description
  of the tracker and one test description agree with the code, and one
  sentence of the ADR amendment that only recorded a change went away.
- The Standards axis named the glossary as a gap, because `CONTEXT.md` has no
  entry for the Connection Lookup. The spec decides that the glossary gains no
  such term, so this ticket adds none.
- Smells that stay, as a judgement: the scanner test stubs set a scanner
  attribute (the spec asks for this), and the search for an Application
  Settings File has the same shape as the search for a composition root.
