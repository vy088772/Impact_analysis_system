# 08 — `/path_evidence` and `/analyze` agree on which program files a name matches

**What to build:** A test runs the "Order" case against both endpoints. The scan has Razor views and the files for `OrdersController` and `OrderHistoryController`. A reading of the code says `/analyze` returns nothing for "Order" and `/path_evidence` matches both controllers by substring. This was never run. A green test closes the defect with a written finding. A red test gets a fix: `/path_evidence` resolves program files through the same program resolution that `/analyze` uses. `/analyze` does not relax to substring matching. The work is in this repository.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The "Order" test runs first, before any production change.
- [ ] The result is written in this ticket: green (no change) or red (the observed answers of each endpoint).
- [ ] If the test is red, both endpoints give the same answer for "Order", and neither matches `OrdersController` by substring.
- [ ] A scan with no Razor files keeps its current answers on both endpoints.
- [ ] The path evidence API test and the exact path evidence test still pass.
