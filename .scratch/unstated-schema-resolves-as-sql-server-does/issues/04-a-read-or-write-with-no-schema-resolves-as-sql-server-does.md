# 04 — A read or write with no schema resolves as SQL Server does

**What to build:** An analyst asks `/find_by_table COMMON.UserProgram` and gets `COMMON.ModuleList_Update` as a proven writer with no mark. The graph builder resolves every read, write, and View or Function reference that states no schema: inside a module in schema `S`, the listing's `S.name`, else `dbo.name`. A reference inside a view or a function resolves against that module's own schema. Every relationship records its schema source.

See "The resolution rule", "The schema source", "The graph builder", and user stories 1 to 7, 10 to 12, 15, 16 in the spec.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A failing graph builder test comes first for each case: a `COMMON` module reading a name that only `COMMON` holds; a `COMMON` module reading a name that only `dbo` holds; a `dbo` module reading a name that `dbo` holds; a name that neither holds; an unlisted name.
- [ ] The lookup crosses object kinds inside one schema: a view `S.X` wins over a table `dbo.X`.
- [ ] A reference inside a view or a function resolves against that view's or function's schema, and the lineage below it follows.
- [ ] A name that neither `S` nor `dbo` holds, an unlisted name, and a `db..name` reference keep an empty schema and the Unproven Schema mark.
- [ ] Every read, write, and function reference relationship carries `schema_source`: `written`, `module_schema`, `default_schema`, or `unresolved`.
- [ ] A resolved schema becomes the node's schema, and the node id follows from it.
- [ ] The default schema is one constant, `dbo`.
- [ ] The golden `path_id` test stays unedited and passes.
- [ ] The graph format version does not change here.
- [ ] The whole suite shows no new failure.
