# A Child Web Application Inherits the Connections of Its Parent Application

**Status:** Accepted
**Date:** 2026-09-30

## Context

ADR-0008 resolves a connection lookup key against `Web.config`. ADR-0018 gives each Project Connection Scope its own table and never merges the tables of two projects.

IIS does not read one `Web.config` alone. A child application runs below the URL of another application, its Parent Application. IIS merges the `<connectionStrings>` and the `<appSettings>` of the parent into the configuration of the child. A call in the child can open a connection that only the parent declares. In the Y-DOCs repository, `Response/Response.Master.cs` opens the connection `PUR`. Only the `Web.config` of TTPUR declares `PUR`. The analyzer read the `Web.config` of Response only. The call had no Resolved Connection Source, and `/find_by_sp` left the caller out of `matches`.

## Decision

The analyzer finds the Parent Application of a web application. The connection lookup table of that application is its own `Web.config` table, plus the entries of each ancestor, nearest first.

- A web application is a project file that declares an IIS URL (`<IISUrl>` in the web project extension).
- Project A is the Parent Application of project B when both IIS URLs have the same scheme, host, and port, and the path of A is a proper prefix of the path of B at a segment boundary. The comparison ignores case and a trailing slash.
- The nearest ancestor has the longest path. When two projects have that longest path, the result is ambiguous and gives no Parent Application.
- The own entry wins over an inherited entry. Across ancestors, the nearest one wins.
- `<connectionStrings>` inherits only from `<connectionStrings>`. `<appSettings>` inherits only from `<appSettings>`. ADR-0008 still keeps the two namespaces apart.
- The chain starts from the project file beside the `Web.config` that supplied the table. This rule also applies to the `Web.config` of the scan root.
- The analyzer finds candidate project files in the whole repository clone. The search stops at the clone root. When the analyzer finds no clone root, it does not search for a Parent Application.
- The analyzer reads the project file and the `Web.config` of an ancestor. It does not scan the code of an ancestor.
- The Application Settings File path does not inherit. ASP.NET Core does not merge the configuration of a parent application.
- The Resolved Connection Source records the declaring file in `declared_in`, as a path relative to the clone root.

The rule uses no System name, no path, and no Database name.

## Consequences

ADR-0018 still holds. The rule does not merge the tables of two sibling projects. It follows a declared parent-child relation, the same relation that IIS follows. Two web applications under one scan root that are not parent and child still never share a table.

The IIS URLs in Y-DOCs match the production layout. The owner of the system confirmed this. An inherited connection is a Resolved Connection Source like any other, and the catalog match of its Database gives `proven`. No new Evidence Status is needed.

The IIS Express `applicationhost.config` under `.vs` is not a source. In Y-DOCs it disagrees with the project files and with the production layout.

The C# Scan Result shape changes, so the scan cache version rises.

Inheritance stops where IIS stops it (`<clear/>`, `<remove>`, and `inheritInChildApplications="false"`). An ambiguous Parent Application gives a visible reason. Both are later work of the same spec.

See [ADR-0008](0008-web-config-connection-string-resolution.md) and [ADR-0018](0018-connection-lookup-tables-are-scoped-to-the-project-file.md).
