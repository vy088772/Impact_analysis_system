# 07 — The two damaged clones repair themselves on their first refresh

**What to build:** A maintainer refreshes the two Systems that could not refresh, and both succeed with no manual git command. The `Y-DOCs` clone held 1521 modified files and the `STC` clone held 60, all of them line-ending differences left by a clone created on Windows and moved to macOS. The decision was to repair them through the new refresh path rather than by hand, so this ticket is that decision's proof.

**Blocked by:** 03, 05, 06

**Status:** done

- [x] A refresh of the `Y-Docs_TTPUR` System succeeds.
- [x] The `Y-DOCs` clone reports a clean working tree afterwards.
- [x] The `STC` clone reports a clean working tree after its own System refreshes.
- [x] Both clones' `meta.json` records a branch, a commit, and a real time.
- [x] Nobody ran a git command against either clone by hand.
- [x] A second refresh of either System also succeeds, and leaves the working tree clean.

**Notes:** Verified against the two real clones at `data/repos/System_Dept_1/Y-DOCs` (1521 modified files beforehand) and `data/repos/System_Dept_1/STC` (60 modified files beforehand) — both carried `core.symlinks=false` and no `meta.json`, matching the spec's description of the Windows-created clones. Each refresh went through the application's own refresh path, `service.repo_manager.resolve_scan_roots(source, refresh=True)`, which calls `AzureDevOpsFetcher.fetch(update=True)` and then `CloneSynchroniser.synchronise()` — no git command was typed by hand against either clone. `source` was built from each clone's own `origin` remote URL and current branch (`project="System Dept 1"`, `repo="Y-DOCs"` or `"STC"`, `branch="TestingPool"`), read from `.git/config` rather than guessed.

First refresh, `Y-DOCs`: succeeded, `git status --porcelain` afterward showed only `?? meta.json` (the project's own definition of clean, per `tests/test_clone_synchroniser.py`'s `_is_clean()` — `meta.json` is an intentional untracked bookkeeping file the synchroniser rewrites on every run, so its presence alone is not dirt). `meta.json` recorded `branch: TestingPool`, `commit: b7ad9f08d1ceb0794ce8f8586fefde54020a52ba`, and a real `refreshed_at` timestamp (not the "unknown" sentinel).

First refresh, `STC`: same outcome — clean afterward, `meta.json` recorded `branch: TestingPool`, `commit: 29e453341a1bd4d9495982f7c7637e0fa548ed2e`, and a real timestamp.

Second refresh of both Systems: both succeeded again and stayed clean (`?? meta.json` only), each `meta.json` updated to a fresh `refreshed_at` while the commit stayed the same (no new upstream commits between the two runs). No lock file was left behind beside either clone directory after either run.

No code changed for this ticket. `tests/test_clone_synchroniser.py` was run afterward as a regression check: 23 passed.
