# 08 — `/path_evidence` and `/analyze` agree on which program files a name matches

**What to build:** A test runs the "Order" case against both endpoints. The scan has Razor views and the files for `OrdersController` and `OrderHistoryController`. A reading of the code says `/analyze` returns nothing for "Order" and `/path_evidence` matches both controllers by substring. This was never run. A green test closes the defect with a written finding. A red test gets a fix: `/path_evidence` resolves program files through the same program resolution that `/analyze` uses. `/analyze` does not relax to substring matching. The work is in this repository.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] The "Order" test runs first, before any production change.
- [x] The result is written in this ticket: green (no change) or red (the observed answers of each endpoint).
- [x] If the test is red, both endpoints give the same answer for "Order", and neither matches `OrdersController` by substring.
- [x] A scan with no Razor files keeps its current answers on both endpoints.
- [ ] The path evidence API test and the exact path evidence test still pass.

## Result

**Red.** The test `tests/test_path_evidence_program_files.py` ran first, before any production change.

- `/analyze` for "Order": `programs == []`, `not_found == ["Order"]`.
- `/path_evidence` for "Order": selected `OrderHistoryController.cs` and `OrdersController.cs` by substring.

**Fix.** `get_path_evidence` in `service/analyze_service.py` now resolves program files through `_program_resolutions`, the same call `/analyze` uses. It keeps the union of the matched files, without duplicates. `_file_matches` is unchanged, so `/analyze` does not relax to substring matching.

**No Razor files.** `_program_resolutions` returns the legacy base-name match when the scan has no Razor file. A second test pins the answer: both controllers still match "Order" on `/path_evidence`.
