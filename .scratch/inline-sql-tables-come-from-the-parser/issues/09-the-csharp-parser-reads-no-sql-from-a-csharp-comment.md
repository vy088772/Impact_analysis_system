# 09 — The C# parser reads no SQL from a C# comment

**What to build:** An analyst sees no table relation from a line of C# code that a programmer commented out. The C# parser now finds SQL text inside a `//` comment or a `/* */` comment of the C# source. The regular expression fallback then gives a table relation for code that never runs.

The rescan of ticket 08 found this defect. It is not in the spec. Before the spec, the function-call guard hid the one local case.

**Blocked by:** None — can start immediately.

**Status:** needs-triage

**The local case:**

- `System_Dept_1/Y-DOCs/ATV/PO_ManifastUploadV3.aspx.cs`, line 131:
  `//this.DbCon.Edit_Data("insert into ManifestNew (R_ID,data) values('" + ... + "')");`
- The live code on line 122 calls the stored procedure `usp_PO_ManifaseUpload_AddData` in place of that insert.
- The C# Scan Result gives `ManifestNew` with the reason `inline_sql_regex` and the access type `UNRESOLVED`, in the method `Initial_IVObject`.
- Line 130 holds the same kind of commented-out insert into `ManifestTemp`. It gives no relation. So the parser is not even consistent about a C# comment.
- Spec user story 11 first called this insert "the real writer". That premise was false. Ticket 08 records the result, and the spec corrected story 11 on 2026-10-01.

**Cause, as far as ticket 08 looked:** `CSharpParser._extract_sql_queries` (`code_analyzer/csharp_parser.py`) runs its SQL patterns on the whole file content. No step removes C# comments first. `strip_sql_comments` removes SQL comments only, inside a SQL text.

**Questions for triage:**

- Remove C# comments before the SQL patterns run, with the line numbers kept? A C# string can hold `//` (for example a URL), so the removal must respect C# string literals.
- How many relations of the ten local Systems come from a C# comment? Ticket 08 counted the relations whose source line starts with `//`, `/*`, or `*`: 14 of the 44 fallback relations (10 in TTRDQ, 3 in TTPUR, 1 in ATV). All 14 carry `UNRESOLVED`, so no `write_only` answer counts them. A comment block that does not start on the relation's line can add more.
- A fix changes a relation, so it needs a C# Scan Result format version rise and a rescan.
