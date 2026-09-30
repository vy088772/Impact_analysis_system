# 05 — A child web application resolves a connection its Parent Application declares

**What to build:** A call in a child web application resolves a lookup key that
only its Parent Application declares. A Parent Application is the web
application whose IIS URL contains the URL of another application as a
sub-path. The analyzer reads the IIS URL from each project file in the
repository clone, also outside the scan root. When the `Web.config` of an
application does not declare a key, the analyzer looks in the Parent
Application, then up the chain. The nearest declaration wins. The Resolved
Connection Source names the configuration file that declared the key. The
rule goes into the Connection Lookup. This ticket is step 2 of the spec. See
the spec, sections "Parent Application", "Inherited lookup tables",
"Evidence", "Scan cache", "Documentation", and "Testing Decisions".

**Blocked by:** 04 — The project scanner and the connection tracker resolve
through the Connection Lookup

**Status:** done (2026-09-30)

- [x] Project A is the Parent Application of project B when both IIS URLs have
      the same scheme, host, and port, and the path of A is a proper prefix of
      the path of B at a segment boundary. The comparison ignores case and a
      trailing slash.
- [x] The analyzer finds candidate project files in the whole repository
      clone. It reads only the project file and the `Web.config` of each
      ancestor. It does not scan the code of an ancestor.
- [x] The application's own entry wins over an inherited entry with the same
      key. Across ancestors, the nearest one wins. A three-level chain
      resolves through the grandparent.
- [x] `<connectionStrings>` inherits only from `<connectionStrings>`.
      `<appSettings>` inherits only from `<appSettings>`.
- [x] A project on a different host or port has no Parent Application.
- [x] A project with no IIS URL, and an ASP.NET Core project, keep their
      current behavior.
- [x] The Parent Application chain starts from the project file beside the
      `Web.config` that supplied the table. This rule also applies when the
      table is the `Web.config` of the scan root.
- [x] The view gives the key-as-name guess only when the own table and each
      inherited table are empty.
- [x] The Resolved Connection Source records the declaring file in the field
      `declared_in`. A key from the application's own `Web.config` names that
      file.
- [x] Each Resolved Connection Source has `declared_in`. A key from an
      Application Settings File names that Application Settings File. A
      key-as-name guess has no declaring file.
- [x] The value of `declared_in` is a path relative to the repository clone.
      When the analyzer finds no clone root, the path is relative to the scan
      root.
- [x] The builder of ticket 02 gains `declared_in`. The project scanner writes
      it to the C# Scan Result.
- [x] The service remap keeps `declared_in` with no change to the remap.
- [x] One function in the analyzer package finds the clone root. The scan
      store uses that same function for the source commit. The function keeps
      the limit of 6 levels.
- [x] The search for the nearest project file stops at the clone root. When
      the analyzer finds no clone root, it does not search for a Parent
      Application.
- [x] The scan cache version rises one time, so an old cache rescans.
- [x] No System name, path, or Database name appears in code or configuration.
- [x] Seam A tests: the step 2 cases of the spec that this ticket owns. Each
      test builds a fixture repository with project files, IIS URLs, and
      `Web.config` files. It makes a Connection Lookup for a scan root that is
      a sub-path. It checks the Database and the declaring file of the answer.
- [x] Scan result check: one test scans a fixture repository with the project
      scanner. It checks that the connection sources of the C# Scan Result
      hold `declared_in`.
- [x] A new ADR records the inheritance rule. ADR-0008 and ADR-0018 each link
      to it. The glossary defines Parent Application, and the Project
      Connection Scope entry mentions it.
- [x] The Resolved Connection Source entry of the glossary names the declaring
      file as a part of the shape.

## Comments

### 2026-09-30 — implementation notes

- New modules: `code_analyzer/clone_root.py` (`find_clone_root`, limit of 6
  levels, used by `service/scan_store.py`) and
  `code_analyzer/parent_application.py` (IIS URL parse, `ParentApplications`).
- `FileConnections` now holds a list of `TableLayer` (own table first, then each
  ancestor). The first layer that declares a key in a namespace answers it. A
  layer that is empty in both namespaces does not count, so the key-as-name
  guess shows only when every layer is empty.
- `declared_in` runs from `ConnectionAnswer` through `ConnectionInfo` (also the
  Field-Held Connection copy) and `resolved_entry` to the C# Scan Result.
  `resolved_entry` takes `declared_in` as a required argument, so a caller
  cannot drop it.
- The scan cache version rises from 42 to 43. ADR-0038 is new. ADR-0008 and
  ADR-0018 link to it. `CONTEXT.md` has the new term and two updated entries.
- The IIS URL comparison also treats the default port (80, 443) as the same as
  no port. The spec does not say this. Without it, `http://host/x` and
  `http://host:80/x` would be two hosts.
- Test result in this directory. Before: 16 failed, 1363 passed, with
  `tests/test_search_roles.py` and `tests/test_sp_tables.py` left out (they fail
  at collection). After: the same 16 failures, 1389 passed. The last change was a
  test stub in `tests/test_program_refresh.py` that needed `declared_in`.
- The type check of the changed analyzer modules gives no error.

### 2026-09-30 — decisions for the next tickets

- Story 40 of the spec says "the Parent Application of that file's project".
  The acceptance criterion of this ticket says the chain starts from the project
  file beside the `Web.config` that supplied the table. The code follows the
  criterion. A test pins it: a class library under a scan-root `Web.config`
  inherits through the project beside that `Web.config`.
- When two candidate parents have the same longest path, `parent_of` gives no
  Parent Application and no reason. Ticket 07 adds the reason. The place to
  add it is `ParentApplications.parent_of`.
- Ticket 06 needs parser fields for `<clear/>`, `<remove>`, and `<location>`.
  Each `TableLayer` is the place where the layers stop or lose a key.

### 2026-09-30 — code review

- The Spec axis found no missing acceptance criterion. It named two gaps with
  no test: the service remap keeps `declared_in` (covered by the
  `with_database` test that keeps a field, and by the spec rule that the remap
  does not change), and the rule that only the project file and the `Web.config`
  of an ancestor are read (true by construction).
- The Standards axis found no hard breach. Changes after the review: the
  `.git` wording of `find_clone_root` (a `.git` file also counts), one dead
  default in `parent_application.py`, and one ragged docstring.
- Smells that stay, as a judgement: `_resolve` in the tracker returns a
  3-tuple, and `ConnectionAnswer` already holds the same fields. A later change
  can return the answer. `parse_iis_url` and `read_iis_url` are public but only
  the class uses them.
