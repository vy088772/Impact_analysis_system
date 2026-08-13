# 01 — Recognize numeric `CommandType` casts as equivalent to named members

**What to build:** `StaticAnalyzerHost`'s existing `CommandType` resolution logic (used by both direct ADO recognition and wrapper-semantics resolution) recognizes a cast of a numeric literal to `CommandType` — e.g. `(CommandType)4` — as equivalent to the named member access it already recognizes (`CommandType.StoredProcedure`). The mapping covers at least `1` → `Text`, `4` → `StoredProcedure`, and `512` → `TableDirect`. This applies uniformly to local source and any future decompiled input — it is not a decompile-only special case.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `IsStoredProcedureCommandType` (direct ADO recognition) recognizes `(CommandType)4` as `CommandType.StoredProcedure`, and analogously for `Text` (1) and `TableDirect` (512)
- [ ] `ContainsStoredProcedureMember` (wrapper-semantics recognition) recognizes the same numeric casts inside wrapper method bodies
- [ ] A numeric cast to a `CommandType` value with no defined mapping (e.g. `(CommandType)999`) is still treated as unresolved/unknown rather than silently misclassified
- [ ] Existing named-member recognition (`CommandType.StoredProcedure`, etc.) is unaffected — no regression in `test_csharp_analysis_gateway.py`'s existing named-member and false-positive cases
- [ ] New unit tests (small synthetic C# fixtures, no decompiler needed) cover: numeric cast for each of the three mapped values, and an unmapped numeric cast staying unresolved
