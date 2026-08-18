# 04 — System-to-Database Catalog Becomes Many-to-Many

**Repo:** `llamaindex-spec-rag`
**Spec:** `Impact_analysis_system/.scratch/database-identity-decoupled-from-system/spec.md`
**ADR:** `docs/adr/0001-system-to-database-is-many-to-many.md`

**What to build:** A System can declare dependence on more than one Database, and a Database with no owning System (like `SysErrorRecord`) becomes representable. `system_catalog.json`'s singular `database: {name, server}` object is replaced with a `databases: [...]` list of database names; a new `SQLServerData.json` becomes the sole registry of `{name, server}` pairs, independent of any System.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] `system_catalog.json`'s per-system `database` field is replaced with `databases: [...]` (a list of database-name strings). `STC`'s entry becomes `databases: ["STC", "SysErrorRecord"]`.
- [ ] A new `SQLServerData.json` lists every known Database as a flat `{name, server}` pair, at minimum `STC`, `PUR`, and `SysErrorRecord` (all on `vmsystest07.topmost.com.tw`, matching what ticket 01's resolution and the real Web.config content confirm).
- [ ] `catalog_builder.py`'s existing manually-curated-field preservation (today covering the singular `database` field) is extended to preserve `databases` across a forced rebuild the same way — a rebuild never drops a System's declared database dependencies, and never invents one for a System that has none.
- [ ] `SQLServerData.json` never contains credentials — only `name` and `server`.
- [ ] `tests/test_catalog_builder_database.py`'s two existing cases (forced rebuild preserves the field; absent field stays absent) are extended to cover `databases` instead of `database`.
