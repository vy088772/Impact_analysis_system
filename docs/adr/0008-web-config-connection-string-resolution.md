# Web.config Connection Keys Are Not Database Names

**Status:** Accepted
**Date:** 2026-08-18

## Context

Connection-source resolution previously treated the AppSettings key or ConnectionStrings name (e.g. `"error"`, `"TTOA"`) as if it were the target database name. This happens to hold for some entries (`key="STC"` really is database `STC`) but breaks for others: `key="error"` is really database `SysErrorRecord`, and `name="TTOA"` is really database `EFNETDB`. Scanned Web.config files also mix two unrelated XML shapes for the same underlying ADO.NET connection-string syntax — `<appSettings><add key="..." value="server=...;database=...;uid=...;pwd=..."/></appSettings>` and `<connectionStrings><add name="..." connectionString="Data Source=...;Initial Catalog=...;User ID=...;Password=..."/></connectionStrings>` — using different synonym keywords for the same fields.

## Decision

Connection-source resolution must parse the actual connection-string *value*, never infer the database (or server) from the AppSettings key / ConnectionStrings name. The parser recognizes both `<appSettings>` and `<connectionStrings>` shapes, matched to which C# accessor produced the candidate (`ConfigurationManager.AppSettings["x"]` vs `ConfigurationManager.ConnectionStrings["x"].ConnectionString`), and resolves `server`/`database`/`uid`/`pwd` through a synonym table (`server`/`Data Source`/`Address`/`Addr` → server; `database`/`Initial Catalog` → database; `uid`/`User ID` → uid; `pwd`/`Password` → pwd). XML comments are skipped by using a real XML parser rather than scanning raw text, so a disabled `<!-- <add .../> -->` entry never produces a resolved connection.

## Consequences

The existing `db_connection_tracker.py` "flexible pattern" (模式4) that uppercases the AppSettings key and uses it directly as the database name is a known-wrong shortcut and must be replaced, not extended.
