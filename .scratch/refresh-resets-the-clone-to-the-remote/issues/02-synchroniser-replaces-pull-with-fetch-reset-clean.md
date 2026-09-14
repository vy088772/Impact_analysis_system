# 02 — A refresh resets the clone instead of merging into it

**What to build:** A maintainer refreshes a System whose clone holds local changes, and the refresh succeeds. The clone ends at the remote's newest commit. This is the failure that started this work: `git pull --ff-only` refused to overwrite modified files and returned a raw git error, and two of the seven clones could never refresh again.

A new seam owns every git operation. It accepts a target directory, a remote URL, and a branch name, and it guarantees one thing: when it returns, the directory equals that branch on that remote. `AzureDevOpsFetcher` keeps only what is specific to Azure DevOps — building the authenticated URL and masking the PAT in errors — and delegates the rest.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A synchroniser accepts a target directory, a remote URL, and a branch name.
- [ ] A refresh fetches, then resets hard onto the remote-tracking ref, then deletes untracked files and directories.
- [ ] The refresh runs that sequence every time, and never first tests whether the working tree is clean.
- [ ] A clone whose tracked files all differ from the remote reaches the remote's newest commit.
- [ ] That clone reports a clean working tree afterwards.
- [ ] A clone holding an untracked file loses that file.
- [ ] `AzureDevOpsFetcher` builds the authenticated URL and masks the PAT, and delegates every git operation.
- [ ] Every clone uses this path; no clone keeps the previous pull behaviour.
- [ ] Tests drive the synchroniser against a local bare repository.
- [ ] No test reaches the network, and no test needs a PAT, an organisation name, or a project name.
- [ ] Tests assert the state of the directory afterwards, never which git commands ran.
