# 09 — A connection string held in a field resolves the same way

**What to build:** A raw ADO.NET call whose connection comes from a field on the calling class
resolves its Resolved Connection Source, so a system that never uses a database
context still answers.

One measured repository is written entirely this way: a controller reads a named
connection string into a field in its constructor, and thirty-five calls open a
connection from that field. Ticket 08 covers the context-type shape; this ticket
covers the field-held shape, using the same per-project lookup table.

**Blocked by:** 08.

**Status:** done

- [x] A field assigned a named connection string resolves calls that open a connection from that field.
- [x] The field's connection resolves through the same Project Connection Scope as every other lookup in that project.
- [x] A field assigned from the root configuration namespace resolves to nothing and names why, matching ticket 08's rule.
- [x] A field whose assigned value cannot be traced stays unresolved and names why.
- [x] The measured repository built in this style resolves the connection for its raw ADO.NET calls.

## Note

### What the measured repository actually showed

ETR does not hold one shape. It holds two, and they disagree:

- Fourteen assignments read `GetConnectionString("dbConnect")` — the ConnectionStrings
  section. These resolve.
- Five controllers read `GetValue<string>("dbConnect")` — the Configuration Root
  Namespace. `dbConnect` exists only under `ConnectionStrings`, so these return null at
  runtime. That is a real configuration defect in the analyzed system, and criterion 3 is
  exactly the rule that keeps it visible instead of resolving it anyway.

Of the thirty-five `new SqlConnection(_connetStr)` call sites, thirty-four take the first
field shape and one — `HomeController.RecordError` — takes the second.

### The blocker nobody had written down

ETR could not be scanned at all. `build_project_connection_scope` read the composition
root with a strict `utf-8-sig` decode, and ETR's `Program.cs` carries Big5 comments, so the
read raised `UnicodeDecodeError` and took the whole scan root's connection resolution with
it. Criterion 5 was unreachable until this was fixed.

The fix is not a local `errors="replace"`. `ProjectScanner` already had the right decoder —
BOM-aware for UTF-16/UTF-32, replacement characters otherwise — as a private static method,
so it moved to `code_analyzer/source_text.py` and both callers now use it. A local copy
would have decoded a UTF-16 `Program.cs` to mojibake and dropped its registrations
silently, which is the failure mode this codebase exists to prevent.

That fix also unblocked ticket 08's shape for ETR: `ETRContext` -> `dbConnect` and
`ErrorLogContext` -> `ErrorLog` now register.

### Where the code is

No new resolver. The field shape is a call-site rule, not a lookup table, so it lives beside
the rules it extends:

- `code_analyzer/source_text.py` — new. One reason to change: how a C# source file's bytes
  become text. `ProjectScanResult._decode_source_bytes` moved here; its single caller and
  `build_project_connection_scope` now share it.
- `code_analyzer/db_connection_tracker.py` — two additions.
  `_ROOT_CONFIGURATION_READS` gained the `GetValue<string>("Key")` form beside the existing
  indexer form, under the same rule. `_extract_sqlconnection_declarations` now records a
  reason when a call site's field does not resolve.
- `code_analyzer/project_connection_scope.py` — the `FIELD_HELD_CONNECTION_NOT_TRACED`
  reason, and the shared decoder.

Criteria 1 and 2 already passed at HEAD: ticket 08's `GetConnectionString` pattern plus the
pre-existing `source_var in self.connections` copy already carried a resolved field to its
call site. Their tests are regression cover, not new behaviour. Only criteria 3, 4 and 5
changed code.

### Three decisions worth stating

**1. The Resolved Connection Source belongs to the call-site variable, not to the field.**
The invocation record names `con`, not `_connetStr`, so a reason attached only to the field
would never be found by the reader who has the invocation. Both get an entry: the field says
why it failed, and the call site inherits that reason verbatim.

**2. One call site resolving does not settle another.** The tracker is keyed by variable
name across a whole file, so two methods each holding a `con` share one entry. An earlier
version skipped recording a reason whenever the name had already resolved somewhere — which
turned the second call site into exactly the silent empty result this ticket forbids. It now
records regardless. When a field name is genuinely ambiguous within one file, the inherited
reason comes from the *nearest* assignment by line, not the first one in the file.

**3. `GetValue<string>("ConnectionStrings:Key")` resolves.** This goes one step past
criterion 3's letter, but refusing it while the indexer form resolves would make the section
prefix mean two different things depending on which reader was used. Ticket 08's rule is the
rule.

### Reasons a connection reports

Ticket 08's four, plus one: `field_held_connection_not_traced` — the field's value traces
back to no lookup key at all (it came from a method call, a parameter, or a constant). It is
recorded only when a Project Connection Scope is in effect; the `Web.config` path never
produced reasons and still does not.

### Verification

New file `tests/test_connection_field_resolution.py`, 11 tests: one per acceptance criterion,
plus the key-absent-from-scope case, the two-call-sites-one-name case, the non-UTF-8
composition root, a `ProjectScanner` end-to-end at the reporting seam, and the ETR
measurement.

Measured, per `new SqlConnection(field)` call site, across all six local repository clones:

```
              before        after
EnterpriseApi  0 / 0         0 / 0
ETR            scan crashed  34 resolved, 1 unresolved (root namespace)
IQCS           0 / 0         0 / 0
RTTalentDB     1 resolved    1 resolved
STC            0 / 0         0 / 0
Y-DOCs         2 resolved    2 resolved
```

No call site in any repository is silently unaccounted for. No repository other than ETR
moves — the WebForms path is untouched, as ticket 08 required.

Scan cache version 30 -> 31: a cached Core scan holds no connection source for these calls.

Full suite before this change: 12 failed, 734 passed, 1 skipped. After: 12 failed, 745
passed, 1 skipped. The twelve are the same twelve, verified by running them at HEAD
(Windows CRLF line endings, a temp-path assertion, wrapper-contract state, and the
out-of-scope uncommitted `Web.config` edits in the Y-DOCs clone). A thirteenth,
`test_external_wrapper_contract_identity.py`, failed once on a Windows file lock and passes
when its file is run alone.

### Found here, belongs elsewhere

**Ticket 08's ambient-context list is short by six names.** Now that these repositories scan,
`_report_unregistered_context_types` claims twenty-four times that the composition root
failed to register a database context type, naming `ClientModelValidationContext` (12),
`AuthorizationFilterContext` (6), `PrincipalContext` (2), `ActionExecutingContext` (2),
`ActionExecutedContext` (1) and `TagHelperContext` (1). Every one is an ASP.NET or
System.DirectoryServices type, and none opens a database. These are confident false claims
that ticket 16's coverage report would inherit. The fix is six names in
`_AMBIENT_CONTEXT_TYPES`, but the rule is ticket 08's, so it is not changed here.

**Field-Held Connection has no ADR.** The decision in point 1 above — the Resolved
Connection Source attaches to the call-site variable — is a real decision with a real
alternative, and `CONTEXT.md`'s entry cites no ADR while its neighbours do. Worth one if the
rule is ever questioned.
