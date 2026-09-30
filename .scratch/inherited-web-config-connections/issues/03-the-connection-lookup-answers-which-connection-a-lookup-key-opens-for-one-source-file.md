# 03 — The Connection Lookup answers which connection a lookup key opens for one source file

**What to build:** A new module, the Connection Lookup, answers one question:
which connection does a lookup key open for one source file. It owns the
nearest project file, the own table of that project, and the reason for a
failed lookup. The module stays beside the current structures in this ticket.
No caller uses it, so no scan output changes. This ticket is the first half of
step 1 of the spec. See the spec, sections "Connection Lookup" and "Testing
Decisions" (Seam A, step 1 cases).

**Blocked by:** 02 — One module reads, remaps, and builds a connection source
entry

**Status:** done (2026-09-30)

- [x] The analyzer can make one Connection Lookup for one scan root. The
      Connection Lookup gives one view for each source file. The names are
      `ConnectionLookup`, `FileConnections`, and `ConnectionAnswer`.
- [x] The view answers a lookup key in one namespace. One answer holds the
      Database, the server, the declaring file, and the reason.
- [x] The answer is a new type. The type that holds a parsed connection string
      value does not gain the declaring file.
- [x] A source file belongs to the nearest project file above it. The search
      has no upper bound, as today.
- [x] If an Application Settings File is beside that project file, the view
      uses it. It wins when a `Web.config` is also there.
- [x] If not, the view uses the `Web.config` beside that project file.
- [x] If the project has neither file, the view uses the `Web.config` of the
      scan root. The search looks in the scan root directory first. It then
      looks in each first-level directory, in name order.
- [x] A source file with no project file above it also uses the `Web.config`
      of the scan root. When the scan root holds an Application Settings File,
      that source file has no table. The answer holds the reason
      `no_project_connection_scope`, and the view makes no guess.
- [x] When the selected `Web.config` table is empty in both namespaces, or no
      `Web.config` exists, the view gives the key-as-name guess. The guess has
      the lookup key as the Database, no server, and no declaring file.
- [x] A failed lookup on the `Web.config` path has no reason, as today.
- [x] The view answers the Context Connection Registration of a context type.
      It also answers whether a Configuration Root Namespace key names a
      connection. On the `Web.config` path, these answers are empty.
- [x] The view shows one read-only fact: whether the source file reads an
      Application Settings File.
- [x] The Connection Lookup reports each Environment Settings Override.
- [x] The answer names the declaring file as a path relative to the scan root.
      Ticket 05 changes the base to the repository clone.
- [x] The Connection Lookup reads no user name and no password (ADR-0010).
- [x] This ticket adds no parser field for `<clear/>`, `<remove>`, or
      `<location>`.
- [x] The current structures and their callers do not change. All current
      tests pass.
- [x] Seam A tests: the six step 1 cases of the spec. Each test builds files,
      gets the view of one source file, and checks the answer.

## Comments

### 2026-09-30 — implementation notes

- The module is `code_analyzer/connection_lookup.py`. The test file is
  `tests/test_connection_lookup.py`. This ticket added these two files and
  changed no other source file.
- `ConnectionLookup(scan_root).for_file(source_file)` gives the view. The view
  has these members:
  - `lookup(key, namespace)` gives a `ConnectionAnswer`.
  - `context_registration(context_type)` gives a `ContextRegistration`. It
    holds the lookup key and the reason.
  - `registered_context_types` lists the registered context types in name
    order. The tracker needs this list for its declaration search.
  - `names_a_connection(key)` answers the Configuration Root Namespace
    question.
  - `reads_application_settings_file` is the read-only fact.
- `ConnectionLookup.environment_overrides()` reports each Environment Settings
  Override. The entries are the same as the entries of the project-scope
  index.
- The module has three namespace constants: `APP_SETTINGS`,
  `CONNECTION_STRINGS`, and `ROOT_CONFIGURATION`. Their values are the same as
  the values of the tracker constants.
- `reads_application_settings_file` is also true for a source file that has
  the reason `no_project_connection_scope`. Today the tracker uses its
  Application Settings File rules for that file, so the fact must agree.
- `ContextRegistration` and `registered_context_types` are not in the spec.
  Ticket 04 needs them to write the same unresolved records as today.
- Test result in this directory. Before: 16 failed, 1310 passed, 2 collection
  errors. After: 16 failed, 1327 passed, 2 collection errors, then 3 more
  tests of the new file, which pass. Each failure is in the baseline. The new
  file has 20 tests. The type check of the new module gives no error.
- A comparison script asked the current structures and the new view for each
  key of each `.cs` file in the local clones. The scan roots were the 6
  repository directories and the 12 first-level directories of Y-DOCs. The
  Database, the server, the reason, and the fact agree in each case. This is
  not the acceptance of step 1. Ticket 04 does the scan comparison.

### 2026-09-30 — notes for ticket 04

- The module imports four things from `code_analyzer/project_connection_scope.py`:
  the reason constants, `PROJECT_FILE_SUFFIXES`,
  `build_project_connection_scope`, and `ProjectConnectionScopeIndex`.
- It uses `ProjectConnectionScopeIndex(scan_root).enabled` to find whether the
  scan root holds an Application Settings File. When ticket 04 removes the
  index, move that directory search and its list of ignored directories into
  the Connection Lookup.
- The search for the nearest project file is a copy of the search of the
  index. `_find_key` is a copy of the tracker lookup. Ticket 04 removes the
  two originals.
- The view tests three private values in three methods to select its
  behavior. The code review named this as a possible smell. Ticket 05 adds
  inherited tables to the view, so this ticket did not reshape it.

### 2026-09-30 — three results that differ from the current structures

- The view uses an Application Settings File beside the project file in each
  case (rule 2 of the spec). The project-scope index uses it only when the
  search of the scan root finds an Application Settings File. The two differ
  in two layouts: a project file above the scan root, and a settings file
  that is only below an ignored directory name such as `dist`. No local scan
  root has these layouts.
- A `Web.config` that is not readable as UTF-8 gives the key-as-name guess and
  a printed warning. Today that file stops the scanner at its start. The
  module reads the `Web.config` of each project, so one bad file must not
  stop the scan.
- A project file above the scan root gives a declaring file that starts with
  `../`. Ticket 05 changes the base to the repository clone.

### 2026-09-30 — code review

- The code review had two axes (Standards and Spec). It found no hard
  violation and no missing requirement.
- Changes after the review: the UTF-8 result above, a module description that
  names ADR-0018 and its amendment, and three more tests.
