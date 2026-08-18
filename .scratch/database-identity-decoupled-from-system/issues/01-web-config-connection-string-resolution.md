# 01 — Web.config Connection Keys Resolve to Real Database Names

**Repo:** `Impact_analysis_system`
**Spec:** `.scratch/database-identity-decoupled-from-system/spec.md`

**What to build:** Connection-source resolution parses the real connection-string value out of Web.config — never the AppSettings key or ConnectionStrings name — and carries the resolved database *and* server all the way through the C# analysis pipeline. Today, `ConfigurationManager.AppSettings["error"]` resolves to a fabricated database `"ERROR"` (the uppercased key) instead of the real database `SysErrorRecord`; `ConfigurationManager.ConnectionStrings["TTOA"].ConnectionString` resolves to `"TTOA"` instead of the real database `EFNETDB`. After this ticket, both resolve correctly.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] A new Web.config connection-string resolver parses `<appSettings><add key="..." value="..."/></appSettings>` entries into `{server, database}`, correctly handling `server=vmsystest07;uid=LogUser;pwd=topmost;DataBase=SysErrorRecord` → `{server: "vmsystest07", database: "SysErrorRecord"}`.
- [ ] The same resolver parses `<connectionStrings><add name="..." connectionString="..."/></connectionStrings>` entries, correctly handling `Data Source=vmsystest07.topmost.com.tw;Initial Catalog=PUR;User ID=webaccess;Password=topmost` → `{server: "vmsystest07.topmost.com.tw", database: "PUR"}`.
- [ ] Key synonyms are resolved through one table covering `server`/`Data Source`/`Address`/`Addr` → server, `database`/`Initial Catalog` → database, `uid`/`User ID` → uid, `pwd`/`Password` → pwd.
- [ ] The resolver uses a real XML parser, so a commented-out `<!-- <add name="ErrLog" .../> -->` entry never produces a resolved connection (verified against `Y-DOCs/Response/Web.config`'s actual dead `ErrLog` entry).
- [ ] `ConnectionInfo` (`db_connection_tracker.py`), `connection_sources` (`project_scanner.py`), and `DbInvocation` (`csharp_analysis_gateway.py`) each gain a `server` field alongside `database`.
- [ ] `db_connection_tracker.py`'s existing "模式4" heuristic (uppercasing the AppSettings key and using it as the database name) is removed, not left running alongside the new resolver.
- [ ] End-to-end: scanning `STC/Global.asax.cs` produces a `connection_sources` entry for `cn` with `database=SysErrorRecord`, `server=vmsystest07` (unnormalized — normalization is ticket 02/03's concern).
- [ ] `tests/test_connection_tracking.py` covers: the `error`→`SysErrorRecord` case, the `TTOA`→`EFNETDB` case, an `<appSettings>` case, a `<connectionStrings>` case, and the commented-out-entry case.
