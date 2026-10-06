# 03 — Mark a temp table lineage read as indirect

**What to build:** A decision on a mark for a correct temp table lineage read. `dbo.usp_DevQryContrast_Qry2` reads `#tmpCus`, and the writers of `#tmpCus` read `Customers`, `DevPart`, and `Part`. `/find_by_table Customers` lists the read as a direct read. The answer does not show that the read passes through `#tmpCus`.

A read of a View or a Function already has a mark. An Execution Path access record gives `is_indirect: true`. An inline table relation gives `read_through` with the name of the View or the Function. A temp table lineage read has neither, but the graph keeps its chain in the `lineage` field.

Source: issue 01 of this directory, which first asked this question for a read that ADR-0043 now removes.

**Blocked by:** None — can start immediately.

**Category:** enhancement

**Status:** needs-triage

- [ ] A decision: keep the current answer, or mark a temp table lineage read as indirect.
- [ ] If the decision is to mark, a spec that states the mark and the readers that show it.
