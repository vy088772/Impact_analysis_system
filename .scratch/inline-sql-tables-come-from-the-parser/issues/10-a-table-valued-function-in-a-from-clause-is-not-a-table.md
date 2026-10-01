# 10 — A table-valued function in a FROM clause is not a table

**What to build:** An analyst does not see a table-valued function as a table. The analyzer host reports a function call in a `FROM` clause, such as `FROM [dbo].[fun_GetRoleOrderTypeList](@Role, '')`, in the read tables of its operation. It does not report it in the function references. So the function becomes a table relation with the access type `SELECT`.

The rescan of ticket 08 found this change. The spec states "A function reference gives no relation", but the host does not call this a function reference.

**Blocked by:** None — can start immediately.

**Status:** needs-triage

**The local cases (rescan of 2026-10-01):**

- 6 parsed relations of TTPUR name a function: `fun_SplitToTable` (`HomePage1.aspx.cs` line 142), and `dbo.fun_GetRoleOrderTypeList` (`PUR_BillConfirm.aspx.cs` 55, `PUR_POPublish.aspx.cs` 65, `PUR_BalanceOrder.aspx.cs` 100, `PUR_SOMaintain.aspx.cs` 162, `PUR_SOPublish.aspx.cs` 36).
- Before the rescan, the function-call guard of the regular expressions dropped them.
- `HostSqlTextAnalysis` gives `read_tables = (dbo.fun_GetRoleOrderTypeList,)` and `function_references = ()` for the text of `PUR_BillConfirm.aspx.cs` line 55.

**The SQL Execution Graph has the same rule:** in the PUR SQL cache, the operation `dml_operation:stored_procedure:dbo.usp_SO_Publish:2` has `read_tables = [dbo.fun_GetRoleOrderTypeList]` and no function reference. So the inline answer and the graph answer agree today (user story 1). A fix belongs in the host, and it changes both places.

**Questions for triage:**

- Should the host report a table-valued function reference (ScriptDom `SchemaObjectFunctionTableReference`) as a function reference? A graph format rise and a SQL cache rebuild follow, and a C# Scan Result format rise and a rescan.
- Or is a read of a table-valued function a useful dependency, so that `/find_by_table fun_GetRoleOrderTypeList` correctly names its callers? Then only the spec sentence needs a correction.
