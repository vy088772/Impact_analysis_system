# 03 — A clone holds the same bytes whatever host created it

**What to build:** A maintainer moves a clone between a Windows machine and a macOS machine, and git reports no change. Today Git for Windows converts every line ending as it writes a file to disk, macOS git converts nothing, and the two hosts therefore disagree about every file in the clone. That disagreement is what made two clones permanently unrefreshable.

The refresh states its line-ending behaviour in the git command itself, so the host's own git configuration cannot change the result. This follows the existing practice of disabling the credential helper per command.

**Blocked by:** 02

**Status:** done

- [x] Every git command that writes the working tree carries an explicit argument turning line-ending conversion off.
- [x] The clone, the fetch, and the reset all carry it.
- [x] No clone's own git config records the setting.
- [x] A clone created with the conversion enabled holds byte-identical content, after one refresh, to a clone created with it disabled.

**Notes:** `code_analyzer/clone_synchroniser.py`'s `_git()` gained a `pin_line_endings` flag that, when set, inserts `-c core.autocrlf=false` right after `git` — the same style already used for `-c credential.helper=`. `_clone()`, the `fetch` call inside `_fetch()` (not the `remote set-url` call, which touches no file), and `_reset_hard()` now pass `pin_line_endings=True`; `_clean()` does not, since deleting untracked files involves no line-ending conversion. Because the setting rides in on `-c` rather than `git config --local`, it is never written into the clone's own config file — confirmed by a new test that reads the clone's `--local` config scope only (the test machine's own global git config defaults `core.autocrlf` to `true`, which is exactly what made a naive `git config --get` check pass for the wrong reason; scoping to `--local` was the fix). A second new test builds a clone as if on a host that converts line endings on checkout (`git -c core.autocrlf=true clone …`) alongside a clone made through the synchroniser, refreshes both through `CloneSynchroniser`, and asserts the two hold byte-identical file content afterwards — proving the per-command pin overrides whatever the host's own git configuration says. Both tests live in `tests/test_clone_synchroniser.py`. Full suite: 916 passed, 12 failed, 1 skipped — the same 12 pre-existing CRLF/path-separator failures noted in ticket 02's notes, none touching `clone_synchroniser`, `azure_fetcher`, or `repo_manager`.
