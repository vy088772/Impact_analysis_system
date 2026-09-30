# 06 — A table match record shows its schema source

**What to build:** An analyst reads a `/find_by_table` record and sees how its schema was found. Every record carries `schema_source`, taken from the graph relationship. An inline C# SQL table that states no schema resolves at question time: it takes `dbo` when the Object Location Index of the connection's Database holds `dbo.name`, and keeps the Unproven Schema mark otherwise. The question opens no cache.

See "The schema source", "The C# side" (the inline C# SQL table match), and user stories 17 to 20 in the spec.

**Blocked by:** 04 — A read or write with no schema resolves as SQL Server does (the record takes that ticket's relationship field).

**Status:** ready-for-agent

- [ ] A failing table match test comes first for a record whose target the graph resolved to `module_schema`, and for one with a `written` schema.
- [ ] An inline C# SQL table with no schema, over an index that holds `dbo.name`, gives a record with schema `dbo`, schema source `default_schema`, and no mark.
- [ ] The same table over an index without `dbo.name` keeps the mark and schema source `unresolved`.
- [ ] An inline C# SQL question opens no cache: a test fails the cache loader.
- [ ] A located-database row from `/locate_object` gains no schema source field.
- [ ] The OpenAPI document is regenerated.
- [ ] The whole suite shows no new failure.
