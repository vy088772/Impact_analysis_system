# Connection Lookup Tables Are Scoped to the Project File

**Status:** Accepted
**Date:** 2026-09-09

## Context

ADR-0008 resolves a connection lookup key against `Web.config`. A WebForms repository holds one `Web.config` per application, so the scan root and the configuration file agree on scope, and the question of scope never came up.

An ASP.NET Core repository breaks that agreement. The `EnterpriseApi` repository holds six independent project files and eleven `appsettings.json` files under one scan root. The same key names repeat across them, and they do not name the same database:

```
eHRIS  in EnterpriseApi/appsettings.json  ->  vmsystest08\vmsystest08_pdcs / YMTHRPortal
eHRIS  in TaskRunner/appsettings.json     ->  vmsystest05.topmost.com.tw   / eHRIS
```

Two servers, two databases, one key name. `EIP`, `YMTGroupApp`, `ErrorLog`, `EEP` and `EFNETDB` repeat the same way. A single table per scan root gives one of the two an arbitrary win, and the loser's calls resolve to a database they never open.

## Decision

One connection lookup table covers one project file directory. A `.cs` file belongs to the nearest project file above it. The analyzer never merges two projects' tables, and never widens a table to the scan root.

This is ADR-0008's rule applied to a second axis. That ADR keeps `<appSettings>` and `<connectionStrings>` apart because two namespaces may carry the same key. This one keeps two projects apart for the same reason: a key name is only unique inside the configuration file that declares it.

## Consequences

- One scan root can hold several tables at once. The number of tables is a fact about the repository, not a failure.
- A `.cs` file with no project file above it has no table. Its connections report unresolved rather than borrow a neighbour's table.
- The failure mode this prevents is silent. A merged table produces a confident wrong `{server, database}`, and a wrong database sends the SP Catalog lookup to the wrong cache. An unresolved connection is visible; a wrong one is not.

## Amendment (2026-09-30): a `Web.config` table also covers one Project Connection Scope

The Decision section above gave a project scope only to an Application Settings File table. A `Web.config` table covered the scan root: each source file on the `Web.config` path used the one `Web.config` that the scan root held. Two web applications under one scan root shared that table.

A `Web.config` table now covers one Project Connection Scope, as an Application Settings File table does. The analyzer selects the table of a source file by these rules, in this order:

1. A source file belongs to the nearest project file above it.
2. If an Application Settings File is beside that project file, the analyzer uses it. It wins when a `Web.config` is also there.
3. If not, the analyzer uses the `Web.config` beside that project file. This table is the own table of the project.
4. If the project has neither file, the analyzer uses the `Web.config` of the scan root. The search looks in the scan root directory first. It then looks in each first-level directory, in name order.
5. A source file with no project file above it also uses the `Web.config` of the scan root. One exception applies. When the scan root holds an Application Settings File, that source file has no table, and its connections report `no_project_connection_scope`.
6. When the selected `Web.config` table is empty in the two namespaces, or no `Web.config` exists, the analyzer uses the lookup key as the Database name. This is the key-as-name guess. It has no server.

Rule 4 is the scan root `Web.config` rule. A class library has no configuration file of its own, and its host application supplies its connections at run time. The rule gives that library the `Web.config` of the scan root. The rule does not merge two tables, so the Decision still holds: the analyzer never merges the tables of two projects.

Rule 4 has a known limit. When a scan root holds more than one web application, the rule can select the wrong host for a class library. The analyzer does not read project references to find the host.

The exception in rule 5 keeps the third consequence above. That consequence now applies only to a scan root that holds an Application Settings File.

One module holds these rules: the Connection Lookup (`code_analyzer/connection_lookup.py`).
