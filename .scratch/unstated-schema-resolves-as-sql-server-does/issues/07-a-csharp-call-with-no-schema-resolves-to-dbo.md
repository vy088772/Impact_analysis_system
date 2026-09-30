# 07 — A C# call with no schema resolves to dbo

**What to build:** An analyst reads a C# call to a procedure that states no schema, and the SP Catalog names `dbo.name` as the target when the catalog holds it. The quick single-procedure analyzer follows the same rule: the schema the name states, else `dbo`. Its query for "the one schema that holds the name" goes away.

See "The C# side" and user stories 21 and 22 in the spec.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A failing gateway test comes first: a C# call to `usp_Load` with no schema, over a catalog that holds `dbo.usp_Load` and `COMMON.usp_Load`, matches `dbo.usp_Load` with no Unproven Schema reason.
- [ ] The same call over a catalog without `dbo.usp_Load` keeps the Unproven Schema match reason.
- [ ] The quick analyzer's unstated schema tests change to "stated, else `dbo`". A name that `dbo` does not hold does not exist.
- [ ] The quick analyzer's `schema` argument keeps no default, and its test still checks that.
- [ ] The whole suite shows no new failure.
