# Inherited Web.config Connections

Status: done

This spec covers two repositories. This repository holds the analysis service.
The companion repository, `llamaindex-spec-rag`, holds the evaluation code that
reads `/find_by_sp`. Both repositories change together.

Issue 01 of this directory reported the defect. This spec replaces the
"What to decide" section of that issue with the decisions below.

## Problem Statement

An analyst asks which programs call the stored procedure
`usp_CheckProgramAuth`. The real caller `Response/Response.Master.cs` does not
show in the answer. No diagnostic in the evaluation output tells the analyst
that a caller is missing.

The call opens the connection `PUR`. The `Web.config` of the Response
application declares `PUR` only inside an XML comment. In IIS, Response runs as
a child application of the TTPUR site. A child application inherits the
`<connectionStrings>` of its parent. So at run time the call opens the `PUR`
connection that the TTPUR `Web.config` declares. The owner of the system
confirmed this layout.

The analyzer reads the `Web.config` of the scanned application only. It finds
no `PUR` entry, so the call has no Resolved Connection Source. The procedure
exists in one SP Catalog only, so the Database Invocation gets the Evidence
Status `likely`. `/find_by_sp` keeps a `likely` call out of `matches`. The
routing-expectation lookup in `llamaindex-spec-rag` reads `matches` only. The
caller therefore disappears from both the proven list and the unproven list.

Two separate defects cause the loss:

1. The analyzer does not know that one web application inherits the
   connections of another.
2. `/find_by_sp` gives a `likely` caller no place in its answer that a client
   can read as a caller.

One structural problem makes defect 1 hard to repair. The analyzer keeps its
connection lookup tables in two unrelated structures. One structure holds one
`Web.config` table for each scan root. The other holds one Application Settings
File table for each Project Connection Scope. The connection tracker selects a
structure by its type. A lookup gives back only the Database and the server.
The result has no place for the configuration file that declared the key. A
`Web.config` lookup that fails has no place for a reason.

A second structural problem puts the new field at risk. A connection source
entry is the value that the C# Scan Result holds for one connection variable.
It has two shapes: the Resolved Connection Source and the Legacy Connection
Label. Three modules each test the shape themselves, and each reads the entry
by a different rule. The service remap builds a new entry from two known
fields. A new field therefore disappears in the remap, and no error shows.

## Solution

The analyzer finds the Parent Application of each web application from the
project files in the repository. A Parent Application is the web application
whose IIS URL contains the URL of another application as a sub-path. When the
`Web.config` of an application does not declare a lookup key, the analyzer
looks for the key in the Parent Application, then in its parent, up the chain.
The Resolved Connection Source records the configuration file that declared
the key.

The call in `Response.Master.cs` then resolves to the `PUR` Database. The
catalog match makes it `proven`, and it shows in `matches` again.

`/find_by_sp` also returns each `likely` caller in a new list. `matches` keeps
its current meaning. The routing-expectation lookup puts the new list under
`unproven_programs`. A caller that the analyzer cannot prove stays visible.

The work on the analyzer has three steps. In step 0, one module takes over the
read, the remap, and the stored form of a connection source entry. In step 1,
one module takes over the connection lookup. This spec names that module the
Connection Lookup. It answers one question: which connection does a lookup key
open for one source file. Step 0 and step 1 change no scan output. In step 2,
the Parent Application rule goes into the Connection Lookup.

## User Stories

1. As an analyst, I want `/find_by_sp` to list `Response/Response.Master.cs`
   as a proven caller of `usp_CheckProgramAuth`, so that my impact list holds
   every program that really calls the procedure.
2. As an analyst, I want a call in a child web application to resolve a
   connection that only its Parent Application declares, so that the analyzer
   agrees with what IIS does at run time.
3. As an analyst, I want a resolved connection to name the configuration file
   that declared it, so that I can check the source of an inherited
   connection.
4. As an analyst, I want a connection that the application itself declares to
   win over the same key in a Parent Application, so that the analyzer uses
   the nearest declaration, as IIS does.
5. As an analyst, I want the analyzer to follow more than one level of Parent
   Applications, so that a deeply nested application also resolves its
   connections.
6. As an analyst, I want the nearest ancestor to win when two ancestors declare
   the same key, so that the result matches the IIS configuration merge.
7. As an analyst, I want a `<clear/>` in the `<connectionStrings>` of a child
   application to stop the inheritance of all parent connection strings, so
   that the analyzer does not resolve a key that IIS removed.
8. As an analyst, I want a `<remove name="..."/>` in a child application to
   stop the inheritance of that one key, so that the analyzer does not resolve
   a key that IIS removed.
9. As an analyst, I want a parent section inside
   `<location inheritInChildApplications="false">` to stay out of the child
   application, so that the analyzer respects the parent's own block.
10. As an analyst, I want the same rules to apply to `<appSettings>` keys, each
    namespace inheriting only from the same namespace, so that ADR-0008 still
    keeps the two namespaces apart.
11. As an analyst, I want a web application on a different host or port to have
    no Parent Application, so that an independent site such as Notification
    never borrows the TTPUR connections.
12. As an analyst, I want the analyzer to find a Parent Application outside the
    scan root of the current System, so that a System scanned with a sub-path
    such as `path=Response` still finds TTPUR.
13. As an analyst, I want the search for a Parent Application to stay inside
    the repository clone, so that one repository never borrows connections
    from another repository.
14. As an analyst, I want the analyzer to read only the project file and the
    `Web.config` of a Parent Application, so that a scan of one System does not
    scan the code of another System.
15. As an analyst, I want an ambiguous Parent Application to give no
    inheritance, so that the analyzer never picks one of two candidates by an
    arbitrary order.
16. As an analyst, I want an ambiguous Parent Application to show the reason
    `ambiguous_parent_application`, so that I can see why the connection did
    not resolve.
17. As an analyst, I want a call whose connection stays unresolved to keep its
    current Evidence Status, so that this change does not demote any call.
18. As an analyst, I want a project file with no IIS URL to have no Parent
    Application, so that a console job or a library keeps its current
    behavior.
19. As an analyst, I want an ASP.NET Core project to keep its current
    Application Settings File behavior, so that the rule does not apply where
    IIS does not merge the configuration.
20. As a client of `/find_by_sp`, I want each `likely` caller in a separate
    list, so that I can show it as an unproven caller.
21. As a client of `/find_by_sp`, I want `matches` to keep only proven callers,
    so that my current code does not read a `likely` caller as proven.
22. As a client of `/find_by_sp`, I want each entry in the new list to carry
    the Evidence Status and the reason, so that I can explain why the caller
    is not proven.
23. As a client of `/find_by_sp`, I want `diagnostics` to stay as it is, so
    that a current reader of `diagnostics` does not break.
24. As an evaluation maintainer, I want the routing-expectation lookup to put
    each `likely` caller under `unproven_programs`, so that no real caller
    disappears with no trace.
25. As an evaluation maintainer, I want a regeneration with `--seeds-from` to
    put `response.master` back in sp-001 as a proven caller with no hand edit,
    so that the reviewed expectations come from the analyzer only.
26. As an evaluation maintainer, I want the `review_notice` of the generated
    expectations and the generated-versus-candidate report to record the
    sp-001 change, so that a reviewer sees why sp-001 changed.
27. As a maintainer, I want the rule to hold no System name, no path, and no
    Database name in code or configuration, so that it works for every System
    with no list per System.
28. As a maintainer, I want an ADR that records the inheritance rule and its
    relation to ADR-0008 and ADR-0018, so that a later reader does not see the
    rule as a break of the project-file scope.
29. As a maintainer, I want the glossary to define Parent Application, so that
    specs and tickets use one term for it.
30. As a maintainer, I want an old scan cache to rescan after this change, so
    that no cached C# Scan Result keeps the old unresolved connection.
31. As a maintainer, I want issue 01 to record that the commit that changed the
    sp-001 result was not found, and which hypotheses were excluded, so that
    nobody repeats the same search.
32. As a maintainer, I want one module to hold each rule that selects a
    connection lookup table, so that a change to the inheritance rule touches
    one place.
33. As a maintainer, I want the connection tracker to ask one view for each
    source file, so that the tracker does not select a table by its type.
34. As a maintainer, I want each lookup answer to hold the Database, the
    server, the declaring file, and the reason, so that no caller loses the
    provenance.
35. As a maintainer, I want the Connection Lookup to land before the
    inheritance rule with no change to the scan output, so that a later
    difference comes from the inheritance rule only.
36. As an analyst, I want a `Web.config` table to cover one Project Connection
    Scope, so that two web applications under one scan root never share a
    table.
37. As an analyst, I want a source file in a project with no configuration
    file to use the `Web.config` of the scan root, so that a class library
    keeps the connections of its host application.
38. As an analyst, I want a source file with no table to keep the key-as-name
    guess, so that the Connection Lookup does not demote any call.
39. As an analyst, I want the search for the scan root `Web.config` to use name
    order, so that two machines give the same result.
40. As an analyst, I want a source file that uses the scan root `Web.config` to
    inherit from the Parent Application of that file's project, so that a class
    library file and a page of one application resolve a key to the same
    Database.
41. As an analyst, I want a Resolved Connection Source from an Application
    Settings File to name that file also, so that each Resolved Connection
    Source has one shape.
42. As an analyst, I want the declaring file as a relative path, so that the
    scan result does not hold a directory of one machine.
43. As an analyst, I want a failed `Web.config` lookup to record a reason only
    for an ambiguous Parent Application, so that the coverage numbers of the
    current Systems do not change.
44. As an analyst, I want a project that holds an Application Settings File and
    a `Web.config` to use the Application Settings File, so that an ASP.NET
    Core project keeps its current behavior.
45. As an analyst, I want the declaring file to stay on a connection that the
    service remaps onto the selected Database, so that the provenance reaches
    the analysis answer.
46. As a maintainer, I want the Connection Lookup to read no user name and no
    password, so that ADR-0010 holds.
47. As a maintainer, I want the command-line database detection to keep its
    own `Web.config` parser, so that the legacy live-connection scan still
    works.
48. As a maintainer, I want ADR-0018 to record that a `Web.config` table also
    covers one Project Connection Scope, so that the code and the ADR agree
    after step 1.
49. As a maintainer, I want the search for the nearest project file to stay
    inside the repository clone after step 2, so that a source file never
    takes a project file from outside its repository.
50. As a maintainer, I want one module to know the two shapes of a connection
    source entry, so that no reader tests the shape itself.
51. As a maintainer, I want a remap onto another Database to keep each other
    field of the entry, so that a new field survives with no change to the
    remap.
52. As a maintainer, I want one function to build the stored form of a
    Resolved Connection Source, so that a new field has one place to go.
53. As a maintainer, I want the stored form to stay a plain mapping, so that
    step 0 does not raise the scan cache version.
54. As a maintainer, I want a Legacy Connection Label to stay readable, so that
    the current tests that use the bare-string shape do not change.
55. As an analyst, I want step 0 to change no analysis answer, so that a later
    difference comes from step 1 or step 2 only.
56. As a maintainer, I want the placeholder rule to stay in the gateway, so
    that the service output does not change in step 0.
57. As a maintainer, I want the name of the shape check to say that it checks
    the shape, so that no reader thinks it excludes a key-as-name guess.
58. As a maintainer, I want the service to keep the decision of which entries
    to remap, so that the entry module knows no SQL cache scope.
59. As a maintainer, I want step 0 to land before step 1, so that step 1
    writes each entry through the one builder.
60. As a maintainer, I want one test file to cover both shapes of an entry, so
    that a change to the read rule has one place to fail.
61. As a maintainer, I want the analyzer to hold no unused entry helper and no
    wrong entry type, so that the code does not mislead the next reader.
62. As a maintainer, I want the glossary entry for Resolved Connection Source
    to name the declaring file after step 2, so that the glossary and the
    stored form agree.
63. As a client of `/find_by_sp`, I want a `likely` caller with no source file
    to stay out of `likely_matches`, so that each entry of the new list names
    a program.
64. As a client of `/find_by_sp`, I want that caller to stay in `diagnostics`,
    so that the caller does not disappear.
65. As a maintainer, I want the split by Evidence Status to stay inside the
    `/find_by_sp` service function, so that the other endpoints do not change.

## Implementation Decisions

### Delivery order

- The work on the analyzer has three steps, in a fixed order. Step 0 builds
  the connection source entry module. Step 1 builds the Connection Lookup.
  Step 2 adds the Parent Application rule to the Connection Lookup.
- Step 0 and step 1 change no scan output. They do not raise the scan cache
  version.
- Step 1 starts only after step 0 is complete. Step 2 starts only after step 1
  is complete.
- The acceptance of step 0 is the test suite. The new tests and the current
  tests must pass. Step 0 needs no scan comparison.
- The maintainer takes the test baseline in the same directory as the change.
  The results of three tests depend on the path of the working directory.
- The acceptance of step 1 is a comparison of two scans. A maintainer scans
  the 10 local scan roots before the change and after the change. The
  connection sources and the unresolved connections must be the same. The
  maintainer records the result in the ticket.
- The scan for this comparison calls the project scanner directly. The scan
  cache does not rescan, because step 1 does not raise its version.

### Connection source entry

- A connection source entry is the value that the C# Scan Result holds for one
  connection variable of one source file. It has two shapes. A Resolved
  Connection Source is a mapping. A Legacy Connection Label is a bare string.
- Step 0 adds one module to the analyzer package. The project scanner, the
  gateway, and the analysis service use it. It is the only place that knows
  the two shapes.
- The module has five functions: `database_of`, `server_of`,
  `has_resolved_shape`, `with_database`, and `resolved_entry`.
- `database_of` gives the Database name as text with no space at each end. It
  gives empty text when the entry has no Database.
- `server_of` gives the server. It gives no value when the server is absent or
  blank. A Legacy Connection Label has no server.
- `has_resolved_shape` is true for a mapping. It examines the shape only. A
  key-as-name guess has the mapping shape, so the function is true for it.
- `with_database` gives an entry for another Database. For a mapping, it
  copies each field and replaces only the Database. For a Legacy Connection
  Label, it gives the new Database name as a bare string.
- `resolved_entry` builds the stored form from a Database and a server. The
  result has the same fields and values as the entry that the project scanner
  writes today.
- The stored form stays a plain mapping. A typed description records its
  fields, but the run-time value is a plain mapping.
- The project scanner builds each entry with `resolved_entry`. Its two private
  entry helpers go away. One of them had no caller.
- The gateway reads an entry with the module. It keeps two rules of its own.
  The first treats the text `unknown` and `unresolved` as no Database. The
  second finds a connection expression with no regard to case.
- The analysis service loses its three private entry helpers. It keeps the
  decision of which entries to remap. That decision depends on the selected
  SQL cache scope and its aliases (ADR-0009), not on the shape of an entry.
- The execution path builder declares a wrong type for its entries. Step 0
  corrects that type.
- The coverage report and the wrapper discovery tool only pass entries to the
  gateway. They do not change.
- Step 0 needs no ADR. It makes no decision that is hard to reverse.

### Connection Lookup

- The Connection Lookup is the one module that selects a connection lookup
  table for a source file. The analyzer makes one Connection Lookup for each
  scan root.
- The Connection Lookup gives one view for each source file. The project
  scanner gives the connection tracker the view of the file that it reads. The
  tracker does not select a table by its type.
- The view answers a lookup key in one namespace. The answer holds the
  Database, the server, the declaring file, and the reason. One answer holds
  all four, so a caller cannot lose the reason.
- The answer is a new type. The type that holds a parsed connection string
  value does not gain the declaring file. That type knows the value only, not
  the configuration file.
- The view also answers the two questions of the Application Settings File
  path. The first is the Context Connection Registration of a context type.
  The second is whether a Configuration Root Namespace key names a connection.
  On the `Web.config` path, these answers are empty.
- The view shows one read-only fact: whether the source file reads an
  Application Settings File. Two tracker rules read this fact, and both stay
  in the tracker, because they know C# code shapes.
  - On the `Web.config` path, a `GetConnectionString` read always uses the
    lookup key as the Database name.
  - The tracker records the reason for an untraced Field-Held Connection only
    on the Application Settings File path.
- The names are `ConnectionLookup` for the module class, `FileConnections` for
  the view, and `ConnectionAnswer` for the answer. The tracker parameter for
  the view has the name `connections`.
- The view selects a table by these rules, in this order:
  1. A source file belongs to the nearest project file above it.
  2. If an Application Settings File is beside that project file, the view
     uses it. It wins when a `Web.config` is also there.
  3. If not, the view uses the `Web.config` beside that project file. This
     table is the own table of the project.
  4. If the project has neither file, the view uses the `Web.config` of the
     scan root. The search looks in the scan root directory first. It then
     looks in each first-level directory, in name order.
  5. A source file with no project file above it also uses the `Web.config`
     of the scan root. One exception applies. When the scan root holds an
     Application Settings File, that source file has no table. It records the
     reason `no_project_connection_scope`, and the view makes no guess.
  6. When the selected `Web.config` table is empty in both namespaces, or no
     `Web.config` exists, the view gives the key-as-name guess.
- The key-as-name guess is the current fallback that uses the lookup key as
  the Database name. It has no server and no declaring file. The view gives
  this guess, so the tracker has no branch for it.
- A `Web.config` table now covers one Project Connection Scope, as an
  Application Settings File table does. This extends ADR-0018.
- The Connection Lookup takes over the report of each Environment Settings
  Override.
- The project-scope index of ADR-0018 goes away. Its rules move into the
  Connection Lookup. The two configuration parsers stay pure parsers.
- The project scanner no longer uses the file search of the legacy
  configuration parser to find the `Web.config`.
- The command-line database detection keeps the legacy configuration parser.
  That detection reads the user name and the password of a connection string.
  ADR-0010 forbids the Connection Lookup to read them.
- In step 1, the answer holds the declaring file, but the project scanner does
  not write it to the C# Scan Result. Step 2 writes it.
- In step 1, the answer names the declaring file as a path relative to the
  scan root, because the clone root function arrives in step 2. Step 2 changes
  the base to the repository clone.
- The project scanner builds each stored entry with the builder of step 0.
  Step 1 does not build a mapping by hand.
- In step 1, the search for the nearest project file has no upper bound, as
  today. Step 2 adds the bound.
- Step 1 does not add the parser fields that `<clear/>`, `<remove>`, and
  `<location>` need. The work that reads those elements adds them.

### Parent Application

- A web application is a project file that declares an IIS URL. Visual Studio
  writes the IIS URL into the web project extension of the project file. The
  IIS URL is the address at which IIS runs that project.
- Project A is the Parent Application of project B when both IIS URLs have the
  same scheme, host, and port, and the path of A is a proper prefix of the path
  of B at a segment boundary. The path comparison ignores case and a trailing
  slash.
- When more than one project qualifies, the nearest ancestor is the one with
  the longest path. If two projects have that same longest path, the Parent
  Application is ambiguous.
- Two projects with the same IIS URL also make an ambiguous result for each
  other.
- An ambiguous result gives no Parent Application. The analyzer records the
  reason `ambiguous_parent_application` in the unresolved connections of the
  scan result. The reason does not reach the rating of the Database
  Invocation, so the Evidence Status of the call does not change.
- `ambiguous_parent_application` is the only reason that the `Web.config` path
  records. Each other failed `Web.config` lookup stays silent, as today.
- The Parent Application chain starts from the project file beside the
  `Web.config` that supplied the table. This rule also applies when the table
  is the `Web.config` of the scan root.
- The analyzer finds candidate project files in the whole repository clone,
  not only in the scan root. The clone root is the directory that holds the
  `.git` directory, as the scan store already finds it for the source commit.
- One function in the analyzer package finds the clone root. The scan store
  uses that same function for the source commit. The function keeps the
  current limit of 6 levels.
- The search for the nearest project file stops at the clone root. When the
  analyzer finds no clone root, it does not search for a Parent Application.
- The analyzer reads only the project file and the `Web.config` of each
  ancestor. It does not scan the code of an ancestor.
- The IIS Express `applicationhost.config` under `.vs` is not a source. In
  Y-DOCs it disagrees with the project files and with the production layout.
- The rule uses no name list. No System name, path, or Database name appears
  in code or configuration.

### Inherited lookup tables

- The connection lookup table of a web application is its own `Web.config`
  table, plus the inherited entries of each ancestor, nearest first. An entry
  that the application declares wins over an inherited entry with the same key.
- `<connectionStrings>` inherits only from `<connectionStrings>`.
  `<appSettings>` inherits only from `<appSettings>`. ADR-0008 keeps the two
  namespaces apart, and inheritance does not merge them.
- The `Web.config` parser learns `<clear/>` and `<remove>` in both namespaces.
  A `<clear/>` in a child section stops all inheritance for that namespace
  from above that level. A `<remove>` stops one key.
- A section inside a `<location>` element with
  `inheritInChildApplications="false"` does not pass to child applications.
- A section inside a `<location>` element with an empty `path` or the `path`
  `.` serves the application of its own file. Without
  `inheritInChildApplications="false"`, it also passes to child applications.
  Each application reads its sections in one document order. (Amendment of
  2026-10-01.)
- A `<clear/>` or a `<remove>` inside a `<location>` element with
  `inheritInChildApplications="false"` stops the inheritance of its own
  application only. A child application does not see it. (Amendment of
  2026-10-01, for story 7.)
- The inheritance rule applies only to the `Web.config` path. The Application
  Settings File path of ADR-0018 does not inherit.
- The Resolved Connection Source gains the configuration file that declared
  the key, in the field `declared_in`. A key from the application's own
  `Web.config` names that file.
- Each Resolved Connection Source has this field. A key from an Application
  Settings File names that Application Settings File.
- The value of `declared_in` is a path relative to the repository clone. When
  the analyzer finds no clone root, the path is relative to the scan root.
- A key-as-name guess has no declaring file.
- After step 2, the view gives the key-as-name guess only when the own table
  and each inherited table are empty.
- This rule removes the guess from a child application whose own table is
  empty, when an ancestor declares an entry. This disagrees with story 17,
  which says that this change does not demote any call. The code follows this
  rule. Issue 11 holds the open decision. On 2026-10-01, each local child
  application had an entry in its own table, so no call lost its Evidence
  Status. (Note of 2026-10-01.)
- Step 2 adds `declared_in` to the builder of the stored form.
- The service remaps a connection onto the selected Database in some cases.
  That remap keeps `declared_in`, because the step 0 operation copies each
  field. Step 2 does not change the remap.

### Evidence

- An inherited connection is a Resolved Connection Source like any other. The
  gateway rates the call against the SP Catalog of that Database. A catalog
  match gives `proven`. No new Evidence Status and no new rating reason are
  needed.
- The owner of the system confirmed that the IIS URLs in Y-DOCs match the
  production layout: TTPUR is the root, Response, ATV, and TTRDQ are children,
  and Notification is an independent site. This confirmation is the basis for
  `proven`.

### Scan cache

- The C# Scan Result shape changes, because the Resolved Connection Source
  gains a field. The scan cache version rises, so an old cache rescans.
- The version rises one time, in step 2. Step 0 and step 1 do not change the
  shape.
- A change to an ancestor `Web.config` changes the HEAD commit of the same
  repository. The current staleness check already compares that commit, so it
  needs no new input.

### `/find_by_sp` contract

- The response gains a list of `likely` callers, named `likely_matches`. Each
  entry has the same shape as an entry of `matches`, with the Evidence Status
  `likely` and the rating reason.
- `matches` keeps only `proven` callers. `diagnostics` does not change.
- An `unresolved` call does not go into `likely_matches`. It stays in
  `diagnostics` only.
- A `likely` call also stays in `diagnostics`, as today.
- A `likely` call goes into `likely_matches` only when the service finds its
  source file. If not, the call stays in `diagnostics` only. `matches` uses
  the same rule for a `proven` call today.
- The split by Evidence Status stays inside the `/find_by_sp` service
  function. No shared function splits the rated calls for more than one
  endpoint.
- `/analyze`, `/find_by_table`, and the flow chain endpoint do not change.

### `llamaindex-spec-rag`

- The stored-procedure lookup reads `likely_matches` beside `matches`. The
  current partition by Evidence Status puts each `likely` caller in the
  unproven half. `unproven_programs` then lists it.
- The regeneration of the routing expectations with `--seeds-from` restores
  `response.master` in sp-001 as a proven caller. The `review_notice` and the
  generated-versus-candidate report record the change.

### Documentation

- Step 1 adds an amendment to ADR-0018. The amendment states that a
  `Web.config` table also covers one Project Connection Scope. It also states
  the scan root `Web.config` rule for a project with no configuration file.
- Step 1 updates the Project Connection Scope entry of the glossary to agree
  with the amendment.
- The glossary gains no term for the Connection Lookup. The glossary holds
  domain facts, and the Connection Lookup is a module.
- A new ADR records the inheritance rule. It links to ADR-0008 and ADR-0018.
  It states that inheritance follows a declared parent-child relation and does
  not merge the tables of two sibling projects, so ADR-0018 still holds.
- ADR-0008 and ADR-0018 each gain a link to the new ADR.
- The glossary gains the term Parent Application. The Project Connection Scope
  entry gains a note that a web application also reads its Parent
  Application's `Web.config`.
- Step 2 updates the Resolved Connection Source entry of the glossary. The
  entry names the declaring file as a part of the shape.
- Issue 01 records the Q1 result: the commit that changed the sp-001 result was
  not found. Two hypotheses were excluded. The ADR-0018 commit did not change
  the `Web.config` path. The `find_by_sp` filter that keeps a non-proven call
  out of `matches` has not changed since 2026-08-12.

## Testing Decisions

- A good test sets up input files, calls one public entry point, and checks
  the output. It does not check private helpers or the order of internal
  calls.
- **Seam A — the Connection Lookup interface.** A test builds a temporary
  repository with project files, IIS URLs, and `Web.config` files. It makes a
  Connection Lookup for one scan root and gets the view of one source file. It
  asks the view for a lookup key in one namespace. It checks the Database, the
  declaring file, and the reason of the answer.
  Step 1 cases:
  - A source file uses the `Web.config` beside its nearest project file.
  - Two projects under one scan root resolve one key to their own Database.
  - A project with no configuration file uses the `Web.config` of the scan
    root.
  - Two first-level directories with a `Web.config` give the first one in
    name order.
  - A source file with no table gets the key-as-name guess.
  - A project with an Application Settings File and a `Web.config` uses the
    Application Settings File.
  - Prior art: the appsettings connection resolution tests.

  Step 2 cases:
  - A child application resolves a key that only its parent declares.
  - The child's own declaration wins over the parent's.
  - A three-level chain resolves through the grandparent, and the nearest
    ancestor wins.
  - `<clear/>`, `<remove>`, and `inheritInChildApplications="false"` each stop
    inheritance.
  - `<appSettings>` inherits only from `<appSettings>`.
  - A project on a different port has no parent.
  - A scan root that is a sub-path of the repository finds a parent outside
    the scan root.
  - Two candidate parents with the same path give no inheritance and the
    reason `ambiguous_parent_application`.
  - A project with no IIS URL keeps its current behavior.
  - A source file that uses the scan root `Web.config` inherits from the
    Parent Application of that file's project.
  - Prior art: the appsettings connection resolution tests.
- **Scan result check — the project scanner.** This is an existing seam. One
  test scans a fixture repository with the project scanner. It checks that the
  connection sources of the C# Scan Result hold `declared_in`. A second test
  checks that the unresolved connections hold `ambiguous_parent_application`.
  Prior art: the project scanner tests in the appsettings connection
  resolution tests.
- **Connection tracker tests.** The current tests give the tracker a parsed
  table. They change to give it a view that the Connection Lookup makes from
  files. No test calls a private lookup helper of the tracker today, so no
  test moves. A tracker with no view keeps the key-as-name guess.
- **Step 1 output comparison.** This is a manual check that runs one time. It
  is not a permanent test, because step 2 changes the output on purpose.
- **Seam D — the connection source entry module.** One new test file calls the
  five functions with plain values and checks the results. Cases:
  - `database_of` and `server_of` read a Resolved Connection Source.
  - `database_of` reads a Legacy Connection Label, and `server_of` gives no
    value for it.
  - An entry with no Database gives empty text.
  - `with_database` keeps the server and one field that the module does not
    know.
  - `with_database` gives a bare string for a Legacy Connection Label.
  - `has_resolved_shape` is true for a mapping and false for a bare string.
  - `resolved_entry` gives the fields that the project scanner writes today.
- **Current tests that stay as they are.** The gateway tests give a Legacy
  Connection Label in 130 places. The execution path integration tests give
  one in 5 places. Four service tests cover the remap decision. Step 0 changes
  none of them, and all must pass.
- **Seam B — the `find_by_sp` service function.** A test gives a scan with one
  `likely` call and one `proven` call to the same procedure. It checks that
  `matches` holds only the proven caller, that `likely_matches` holds the
  likely caller with its Evidence Status and reason, and that `diagnostics`
  does not change. A second case gives a `likely` call with no source file. It
  checks that the call shows in `diagnostics` only. Prior art: the derived
  execution evidence reuse tests.
- **Seam C — the cache-derived lookup in `llamaindex-spec-rag`.** A test gives
  a fake `/find_by_sp` response with one entry in `likely_matches`. It checks
  that `unproven_programs` lists the caller and that the proven list does not.
  Prior art: the cache-derived lookup tests.
- **Acceptance.** A manual regeneration with `--seeds-from` on the real Y-DOCs
  repository puts `response.master` back in sp-001 with no hand edit. This
  step needs a local rescan first, because the scan cache version rises.

## Out of Scope

- Finding the commit that changed the sp-001 result after 2026-09-07. The
  grilling session stopped that search.
- Inheritance from `machine.config` or the root `web.config` of the .NET
  Framework.
- Reading the production IIS configuration. The repository does not hold it.
- A `<location>` element whose `path` is not empty and is not `.`. The parser
  does not read it. (Amendment of 2026-10-01: the first text kept each
  `<location>` element out of scope. Ticket 06 reads the elements with an
  empty `path` or the `path` `.`, and the review of the whole effort accepted
  this. See "Inherited lookup tables" and ADR-0038.)
- `unresolved` callers in the `/find_by_sp` answer. Only `likely` callers gain
  a list.
- Configuration transforms such as `Web.Release.config`.
- Connections that an `App.config` declares. A console project with only an
  `App.config` keeps the key-as-name guess.
- The use of project references to find the host application of a class
  library. The scan root `Web.config` rule can select the wrong host when a
  scan root holds more than one web application.
- A reason for each failed `Web.config` lookup. Only
  `ambiguous_parent_application` gains a record.
- The removal of the command-line database detection and its legacy
  configuration parser.
- The retirement of the Legacy Connection Label shape. A service scan cannot
  write that shape today. Only tests give it.
- A check of resolution by evidence. A key-as-name guess has the mapping
  shape, so the analyzer reads it as a Resolved Connection Source. This does
  not agree with the glossary. A later ticket can use `declared_in` to
  separate the two.
- The placeholder rule for each reader. Only the gateway treats `unknown` and
  `unresolved` as no Database.
- A shared function that splits rated calls by Evidence Status. See Further
  Notes for the reason.
- A `proven` call with no source file that the service can find. Today
  `/find_by_sp` puts it in no list. A repair would change `diagnostics`, so a
  later ticket must make it.

## Further Notes

- The project scanner has one place that writes a connection source entry,
  and it always writes a mapping. The scan cache refuses each cache that has
  an old version. So a Legacy Connection Label does not come from a service
  scan.
- The companion repository does not read the connection sources. Its
  restricted unpickler is not the reason for the plain mapping. The reason is
  that the scan cache version does not rise.
- The first plan for the entry module changed in three places. The three
  readers use three different rules, not one repeated rule. The plain mapping
  has a different reason. The gateway is in the analyzer package, so the
  module goes there.
- Decision record of the entry module session: S1 (a) an own step before step
  2, S2 (a) read both shapes, S3 (a) functions on the plain entry, S4 (a) the
  placeholder rule stays in the gateway, S5 (a) the shape decides resolution,
  S6 (a) only the one-entry operation moves, S7 (a) step 0 before step 1,
  S8 (a) acceptance by the test suite, S9 (a) the name `has_resolved_shape`.
- A session examined one shared function that gives three lists of rated
  calls: `proven`, `likely`, and `unresolved`. The session rejected it.
  - Four endpoints test the Evidence Status in five places. Each place is one
    comparison with the `proven` value.
  - Only `/find_by_sp` needs three lists. Each other place asks only if a call
    is `proven`.
  - The four endpoints use the result in four different ways. `/find_by_table`
    already keeps a call that is not `proven` in `matches` (ADR-0015).
  - Without the function, each caller holds one condition. The function hides
    nothing that a caller does not also know.
- Decision record of the partition session: T1 (a) no shared function, T2 (a)
  a `likely` call with no source file stays in `diagnostics` only, T3 (a)
  record the rejection here, T4 (a) no repair of the `proven` call with no
  source file.
- In the local clones, 10 scan roots hold 6 `Web.config` files. Each
  `Web.config` is beside a project file. The scan root of STC is the clone
  root, and its `Web.config` is one level below.
- The service scan does not reach the command-line database detection. The
  command-line entry point and the legacy scripts reach it.
- The first plan for the Connection Lookup changed in five places. The legacy
  configuration parser stays. No tracker test moves. The tracker keeps one
  per-file view. The view answers more than one question. ADR-0018 gains an
  amendment in step 1.
- Decision record of the Connection Lookup session: R1 (a) step 1 before the
  inheritance rule, R2 (a) scan root `Web.config` for a project with no
  configuration file, R3 (a) keep the key-as-name guess, R4 (a) one view for
  each source file, R5 (a) only `ambiguous_parent_application` on the
  `Web.config` path, R6 (a) each Resolved Connection Source has the declaring
  file, R7 (a) keep the legacy configuration parser, R8 (a) keep the current
  rule for a scan root with an Application Settings File, R9 (a) name order
  for the scan root `Web.config`, R10 (a) one read-only fact on the view,
  R11 (a) a new module, R12 (a) tests build the view from files, R13 (a)
  `declared_in` relative to the clone root, R14 (a) ADR-0018 amendment in
  step 1, R15 (a) a new answer type, R16 (a) the scan root table inherits,
  R17 (a) no bound in step 1 and a clone bound in step 2, R18 (a) a manual
  output comparison.
- In the current repositories, only 6 project files declare an IIS URL, and all
  6 are in Y-DOCs. The rule changes no other System today.
- `service/analyze_service.py` also remaps a file's single Legacy Connection
  Label onto the selected Database. The grilling session did not examine
  whether this remap produced the old sp-001 proof. It is not part of this
  spec.
- Decision record: Q2 (a) IIS URL rule, Q3 (a) show `likely` callers, Q4
  Notification is an independent site, Q5 (a) `proven` with the declaring
  file, Q6 (a) search the repository clone, Q7 (a) new ADR, Q8 (a) separate
  list, Q9 (a) no inheritance when ambiguous.
