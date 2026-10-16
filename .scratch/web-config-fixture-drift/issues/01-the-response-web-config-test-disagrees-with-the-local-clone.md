# 01: The Response Web.config test disagrees with the local clone

**What to build:** Nothing yet. This ticket records a test failure and its decision. `tests/test_connection_tracking.py::TestParseWebConfigConnections::test_commented_out_entries_never_resolve` fails on this machine. Find out whether the local clone is newer than the test, or the test is out of date. Then fix the one that is wrong.

**Blocked by:** None

**Status:** needs-triage

## Evidence

- The test reads `data/repos/System_Dept_1/Y-DOCs/Response/Web.config`. The folder `data/repos` is git-ignored, so the file differs between machines.
- It expects the `PUR` connection and the `ErrLog` connection to be commented out. In the local file, `PUR` (line 14) is active. `ErrLog` (line 16) is commented out.
- The local file dates from Sep 8. The clone's last commit is dated 2026-07-08 (`747989e`).
- The parser (`code_analyzer/webconfig_connection_resolver.py`) behaves correctly: it keeps an active entry and drops a commented one.
- A clean `git worktree` has no `data/repos`. The test skips there (`requires_web_config_fixtures`), so it looks green. This hid the failure.
- The failure also happens on `HEAD` before the scan-store split. The split is not the cause (found in cache-refresh-queue ticket 01).

## Questions

- [ ] Did the Azure repo Y-DOCs change `PUR` from commented to active after the test was written? Check the history of `Response/Web.config`.
- [ ] If the repo changed: update the test expectation, or give the test its own fixture file under `tests/` so it never depends on a live clone.
- [ ] If the clone is wrong: re-clone Y-DOCs and run the test again.

## Comments
