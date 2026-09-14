# Refresh resets the clone to the remote

**Status:** ready-for-agent

**Decision record:** [ADR-0023](../../docs/adr/0023-a-clone-is-a-read-only-mirror-reset-to-the-remote.md)

## Problem Statement

A maintainer runs a refresh for a System and it fails. The service answers HTTP 500 and prints a raw git error that names files the maintainer never edited. The remote changes often, so the maintainer expects the refresh to succeed often. Instead the same System fails on every attempt, and nothing in the message says how to recover.

The cause sits in the local clone, not in the remote. Two clones were created on Windows and now run on macOS. Git for Windows converted every line ending when it wrote those files to disk. macOS git compares raw bytes, so it reports every file in those two clones as modified. `git pull --ff-only` refuses to overwrite a modified file, so it stops.

The failure is permanent, not intermittent. Two of the seven clones are affected, covering 1581 files. Neither clone can ever refresh again until someone repairs it by hand.

## Solution

A refresh stops trying to merge and starts replacing. It fetches the remote, resets the working tree onto the fetched commit, and deletes anything left over. It does this every time, whatever state the working tree is in.

The maintainer sees a refresh that succeeds. The two broken clones repair themselves on their first refresh, with no manual step. A refresh no longer inherits line-ending behaviour from the operating system it runs on, so a clone created on Windows and a clone created on macOS hold identical bytes.

One repository can serve several Systems. A lock stops two Systems from resetting the same clone at the same time. A metadata file beside the code records which branch the clone holds, which commit it stopped at, and when it last refreshed.

## User Stories

1. As a maintainer, I want a refresh to succeed when the clone's working tree holds local changes, so that a dirty mirror never blocks an update.
2. As a maintainer, I want the refresh to discard those local changes without asking me, so that I never repair a mirror by hand.
3. As a maintainer, I want the refresh to run the same steps whether the working tree is clean or dirty, so that its behaviour is easy to predict.
4. As a maintainer, I want the refresh to delete untracked files it finds in the clone, so that leftover build output never reaches the analyzer.
5. As a maintainer, I want the two clones that Windows created to repair themselves on their next refresh, so that I run no manual repair step before this change ships.
6. As a maintainer, I want every clone to follow these rules, not only the clone that several Systems share, so that no clone is left on the old behaviour.
7. As a maintainer, I want a refresh to write the same bytes to disk on Windows and on macOS, so that moving a clone between machines does not mark every file as changed.
8. As a maintainer, I want the refresh to state its line-ending behaviour in the git command itself, so that a machine's own git configuration cannot change the result.
9. As an operator, I want a refresh of one System to block a concurrent refresh of another System that shares the same repository, so that neither sees a half-updated working tree.
10. As an operator, I want the blocked refresh to stop immediately and tell me the mirror is busy, so that I know to retry rather than wait without an estimate.
11. As an operator, I want a lock left behind by a crashed refresh to expire, so that one crash does not block every later refresh.
12. As an operator, I want the lock to survive the refresh that holds it, so that the refresh's own cleanup step cannot delete it.
13. As a maintainer, I want a metadata file to record which branch the clone holds, so that I can read the clone's state without running git.
14. As a maintainer, I want that file to record the commit the clone stopped at, so that I can tell which version the analysis ran against.
15. As a maintainer, I want that file to record when the clone last refreshed successfully, so that I can tell a fresh mirror from a stale one.
16. As a maintainer, I want the metadata file to say plainly that the time is unknown when it is unknown, so that I never read a guessed time as a real one.
17. As a maintainer, I want a missing metadata file to be rebuilt from git, so that losing it costs nothing.
18. As a maintainer, I want a missing metadata file never to trigger a fresh clone, so that one crash does not cost a full download.
19. As a maintainer, I want the branch a System declares in settings to decide which branch the refresh targets, so that settings stay the single place I change it.
20. As a maintainer, I want the refresh to delete and re-create the clone when the declared branch differs from the branch the clone holds, so that a branch change always lands completely.
21. As a maintainer, I want a fresh clone to write its metadata file immediately, so that the next refresh reads a complete record.
22. As an analyst, I want the analyzer to read a clone that matches the remote exactly, so that an impact answer describes the current code.
23. As an analyst, I want a refresh failure to name a cause I can act on, so that I do not read raw git output to understand what happened.
24. As a maintainer, I want the refresh to release its lock when it fails, so that a failed run does not block the next one.
25. As a maintainer, I want the clone to be documented as a read-only mirror, so that nobody treats it as a place to keep work.
26. As a maintainer, I want a refresh to leave no record of what it discarded, so that the implementation stays simple.
27. As a maintainer, I want the refresh to fetch before it resets, so that it resets onto the newest commit rather than the one already on disk.
28. As a maintainer, I want the refresh to keep working against a shallow clone, so that the existing download size does not grow.

## Implementation Decisions

**One new seam owns every git operation.** A clone synchroniser takes a target directory, a remote URL, and a branch name. It guarantees one thing: when it returns, the directory equals that branch on that remote. Fetching, resetting, cleaning, locking, metadata, line-ending pinning, and re-cloning on a branch change all sit behind it. It knows nothing about Azure DevOps, PATs, Systems, or the catalog.

`AzureDevOpsFetcher` keeps only what is specific to Azure DevOps: building the authenticated URL and masking the PAT in errors. It delegates the rest to the synchroniser. `repo_manager` continues to decide the target directory from project and repository names, and continues to resolve scan roots.

**The refresh sequence is fixed and unconditional.** The synchroniser fetches, resets hard onto the remote-tracking ref, and then cleans untracked files and directories. It never inspects whether the working tree is clean first. One code path handles both cases.

**Line-ending conversion is pinned off per command.** Every git command that writes the working tree carries an explicit argument turning the conversion off. This matches the existing practice of disabling the credential helper per command. The setting is never written into a clone's own git config, so a clone created before this change behaves the same as one created after.

**The declared branch is intent; the metadata file is fact.** Settings and the catalog declare the branch. A `meta.json` file inside the clone directory records the branch the clone holds, the commit it stopped at, and the time of the last successful refresh. The time field can hold an explicit unknown value, distinct from both a real time and a missing field.

When the declared branch and the recorded branch differ, the synchroniser deletes the whole directory and clones again. A shallow clone tracks one branch, so fetching a different branch is not available to it.

When `meta.json` is absent, the synchroniser asks git which branch the clone is on and rebuilds the file, recording the time as unknown. An absent file never triggers a re-clone, because the cleaning step deletes that file on every refresh and the synchroniser writes it back afterwards.

**The lock is per directory and lives outside it.** The lock file sits beside the clone directory, not inside it, because the cleaning step would otherwise delete the lock mid-run. The lock is keyed on the clone directory rather than on a System, because several Systems can share one directory. A refresh that finds the lock held returns immediately with a busy result; it does not queue. A lock older than thirty minutes counts as abandoned, and the next refresh takes it over. A refresh releases its lock on failure as well as on success.

**Scope covers every clone.** All seven existing clones and every future clone use this path. No clone keeps the old `git pull --ff-only` behaviour.

## Testing Decisions

A good test here asserts the state of a directory after a synchronise call. It does not assert which git commands ran, in which order, or with which arguments. Those are implementation details that a later change may reorder freely.

Tests drive the clone synchroniser directly, at the new seam. Each test creates a local bare repository, commits into it, and uses it as the remote. No test reaches the network, and no test needs a PAT, an organisation name, or a project name. This is new ground for the suite: no existing test drives real git, and the refresh tests that exist replace `resolve_scan_roots` wholesale rather than exercising the layer beneath it.

Cases to cover:

- A clean clone reaches the remote's newest commit.
- A clone whose tracked files were all rewritten with different line endings reaches the remote's newest commit, and reports clean afterwards.
- A clone holding an untracked file loses that file.
- A clone created with line-ending conversion on holds byte-identical content after a refresh to one created with it off.
- A second synchronise call against a held lock returns busy and changes nothing.
- A synchronise call against a lock older than the timeout proceeds.
- A failing synchronise releases its lock.
- A synchronise writes `meta.json` with the branch, the commit, and a time.
- A synchronise with `meta.json` deleted rebuilds it, records the time as unknown, and does not re-clone.
- A synchronise whose declared branch differs from the recorded branch produces a clone on the declared branch.
- The lock file survives a synchronise that cleans the working tree.

`AzureDevOpsFetcher` keeps its existing behaviour tests for URL construction and PAT masking. Those do not move.

## Out of Scope

- Any change to how a refresh reports failures that are not caused by a dirty working tree. Expired PATs, network failures, and missing branches keep their current messages.
- Any record of what a refresh discarded. This was considered and rejected; reopening it needs a new decision.
- Any mechanism that prevents a person from editing a clone. The read-only mirror rule is documented, not enforced.
- Any change to the shallow clone depth or to the single-branch fetch configuration.
- Any change to what the analyzer does with the files once they are on disk.
- Repairing the two affected clones by hand before this ships. They repair themselves on their first refresh under the new path.

## Further Notes

**A glossary gap.** `CONTEXT.md` carries no term for the local copy of a repository, even though the concept now carries rules of its own: it mirrors one branch, it holds no work, and a refresh replaces it wholly. A term for it belongs in the glossary. This spec uses "clone" throughout and introduces no synonym.

**Why the cause is settled.** Both affected clones carry `core.symlinks=false` in their own git config and the five clean clones carry none. Git for Windows writes that setting. The two affected clones were created on 2026-08-07; the five clean ones on 2026-09-11. Every difference in both clones disappears under `git diff --ignore-space-at-eol`. No code in this repository or in `llamaindex-spec-rag` writes into a clone.

**The fetch already succeeded.** The failed run on 2026-09-11 completed its download. Its remote-tracking ref advanced by seventeen commits and those commits are on disk. Only the working-tree update failed. The first refresh under this change therefore has nothing left to download for that clone.
