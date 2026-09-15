# 02 — A refresh resets the clone instead of merging into it

**What to build:** A maintainer refreshes a System whose clone holds local changes, and the refresh succeeds. The clone ends at the remote's newest commit. This is the failure that started this work: `git pull --ff-only` refused to overwrite modified files and returned a raw git error, and two of the seven clones could never refresh again.

A new seam owns every git operation. It accepts a target directory, a remote URL, and a branch name, and it guarantees one thing: when it returns, the directory equals that branch on that remote. `AzureDevOpsFetcher` keeps only what is specific to Azure DevOps — building the authenticated URL and masking the PAT in errors — and delegates the rest.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A synchroniser accepts a target directory, a remote URL, and a branch name.
- [x] A refresh fetches, then resets hard onto the remote-tracking ref, then deletes untracked files and directories.
- [x] The refresh runs that sequence every time, and never first tests whether the working tree is clean.
- [x] A clone whose tracked files all differ from the remote reaches the remote's newest commit.
- [x] That clone reports a clean working tree afterwards.
- [x] A clone holding an untracked file loses that file.
- [x] `AzureDevOpsFetcher` builds the authenticated URL and masks the PAT, and delegates every git operation.
- [x] Every clone uses this path; no clone keeps the previous pull behaviour.
- [x] Tests drive the synchroniser against a local bare repository.
- [x] No test reaches the network, and no test needs a PAT, an organisation name, or a project name.
- [x] Tests assert the state of the directory afterwards, never which git commands ran.

**Notes:** Added `code_analyzer/clone_synchroniser.py` with `CloneSynchroniser`, the new seam. Its `synchronise(target, remote_url, branch)` clones when `target` holds no `.git`, and otherwise runs `fetch` → `reset --hard origin/<branch>` → `clean -fd` unconditionally, every call, with no check of working-tree state first. `code_analyzer/azure_fetcher.py` now takes an injectable `synchroniser` (default `CloneSynchroniser()`); `AzureDevOpsFetcher.fetch()` still builds the PAT-bearing URL and still masks the PAT in any error the synchroniser raises, but no longer runs `git` itself — `_git_clone`, `_git_pull`, and the old `_run` are gone. `service/repo_manager.py` needed no change: it already calls `fetcher.fetch(update=refresh)`, which now rides the new path. Tests: `tests/test_clone_synchroniser.py` drives `CloneSynchroniser` against a local bare repository (created with `git init --bare`, no network, no PAT/org/project) and covers a dirty tracked file reaching the newest commit, an untracked file and directory being removed, a clean working tree afterwards, and a first-time clone; each assertion reads the directory's state, never the commands run. `tests/test_azure_fetcher.py` covers delegation of the built URL and branch, PAT masking on a synchronise failure, and that `update=False` against an existing clone never calls the synchroniser. Full suite: 914 passed, 12 failed, 1 skipped — the 12 failures are pre-existing and unrelated (CRLF/path-separator assertions in `test_connection_tracking.py`, `test_csharp_analysis_gateway.py`, `test_external_wrapper_discovery.py`, `test_graph_reverse_lookup.py`, `test_program_refresh.py`, `test_repair_sql_execution_graphs.py`, `test_table_reverse_lookup_traffic_record.py`); none touch `azure_fetcher`, `repo_manager`, or `clone_synchroniser`. Ran `/code-review` (Standards + Spec sub-agents): Spec axis found no missing/partial checklist items and no creep into tickets 03–06. Standards axis found no documented-standard violation (repo has no CODING_STANDARDS.md/CONTRIBUTING.md) and two minor duplication smells, both fixed: `CloneSynchroniser` now exposes a static `is_cloned(target)` that `AzureDevOpsFetcher.fetch()` calls instead of re-deriving the `.git`-exists check, and the four git-command builders (`_clone`/`_fetch`/`_reset_hard`/`_clean`) now share one `_git(target, args, with_no_credential_helper=...)` helper instead of each hand-assembling a `['git', '-C', ...]` list. Also tightened the `synchroniser` constructor parameter to `Optional[CloneSynchroniser]`. Re-ran the 7 new tests after the fixes — still 7 passed.
