# 08 — `/path_evidence` and `/analyze` agree on which program files a name matches

**What to build:** A test runs the "Order" case against both endpoints. The scan has Razor views and the files for `OrdersController` and `OrderHistoryController`. A reading of the code says `/analyze` returns nothing for "Order" and `/path_evidence` matches both controllers by substring. This was never run. A green test closes the defect with a written finding. A red test gets a fix: `/path_evidence` resolves program files through the same program resolution that `/analyze` uses. `/analyze` does not relax to substring matching. The work is in this repository.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] The "Order" test runs first, before any production change.
- [x] The result is written in this ticket: green (no change) or red (the observed answers of each endpoint).
- [x] If the test is red, both endpoints give the same answer for "Order", and neither matches `OrdersController` by substring.
- [x] A scan with no Razor files keeps its current answers on both endpoints.
- [x] The path evidence API test and the exact path evidence test still pass.

## Result

**Red.** The test `tests/test_path_evidence_program_files.py` ran first, before any production change.

- `/analyze` for "Order": `programs == []`, `not_found == ["Order"]`.
- `/path_evidence` for "Order": selected `OrderHistoryController.cs` and `OrdersController.cs` by substring.

**Fix.** `get_path_evidence` in `service/analyze_service.py` now resolves program files through `_program_resolutions`, the same call `/analyze` uses. It keeps the union of the matched files, without duplicates. `_file_matches` is unchanged, so `/analyze` does not relax to substring matching.

**No Razor files.** `_program_resolutions` returns the legacy base-name match when the scan has no Razor file. A second test pins the answer: both controllers still match "Order" on `/path_evidence`.

## Review follow-up

The code review of the first commit found these. Each one is closed here.

- **Last checklist item.** It stayed unchecked. `tests/test_path_evidence_api.py` and `tests/test_exact_path_evidence.py` pass, in the first commit and after this follow-up.
- **Red-first order.** The "Order" test ran red before the first production change. Observed answers are in the Result above. The commit holds test and fix together, so the order is not visible in the history.
- **Action ownership.** `/path_evidence` took whole files and dropped the action filter of `/analyze`. It now keeps an invocation only when a resolution owns its action (`_resolution_owns_invocation`, shared with `/analyze`). Test: `test_a_resolved_screen_reaches_only_the_invocations_on_its_own_actions`. It fails when the filter is off.
- **Shared selection.** `_program_resolutions_for_names` collects the resolutions and the de-duplicated files for several names. `/path_evidence` uses it.
- **End to end.** A name that resolves to a screen ("Orders") reaches that screen's controller on `/path_evidence`.
- **No Razor files.** The test now runs `/analyze` and `/path_evidence` on the same scan. Both keep the base-name match.
- **Test helpers.** The scan builders moved to `tests/program_screen_fixtures.py`. `tests/test_program_screen_resolution.py` imports them from there.

Not changed, by decision:

- A name that resolves to nothing leaves `/path_evidence` with no files. It ends in `path_not_found` or `stale_path`. A new error code would change the API contract, and the ticket does not ask for it.
- An empty `program_names` list still selects all files on `/path_evidence`. This difference is older than this ticket and the ticket does not name it.

