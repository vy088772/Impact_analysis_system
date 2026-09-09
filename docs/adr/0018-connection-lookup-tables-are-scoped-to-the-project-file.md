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
