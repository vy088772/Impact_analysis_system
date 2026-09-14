# A Clone Is A Read-Only Mirror That Refresh Resets To The Remote

**Status:** Accepted
**Date:** 2026-09-14

## Context

`service/repo_manager.py` keeps one local clone for each Azure DevOps repository under `data/repos/<project>/<repo>`. A refresh updated that clone with `git pull --ff-only`. That command stops when the working tree holds local changes. It then reports the raw git error to the caller as an HTTP 500.

On 2026-09-11 a refresh of the `Y-Docs_TTPUR` System failed this way. The `Y-DOCs` clone held 1521 modified files, and the `STC` clone held 60 more. Every difference was a line-ending difference. `git diff --ignore-space-at-eol` reported no change at all.

The investigation identified the cause. Both affected clones carry `core.symlinks=false` in their own git config, and the five clean clones carry no such setting. Git for Windows writes that setting at clone time. Git for Windows also sets `core.autocrlf=true` by default, which converts a line feed to a carriage return plus line feed when git writes a file to disk. A person created those two clones on Windows on 2026-08-07. They now run on macOS, where git applies no conversion. macOS git therefore compares the raw bytes and reports every file as modified.

No program in this repository writes into a clone. The dirty state came from moving a checked-out working tree between two operating systems.

Two further facts shape the decision. One repository can serve several Systems: the catalog points both `Y-Docs_TTPUR` and `Y-DOCs_TTRDQ` at the same `Y-DOCs` repository, and each System scans different subdirectories. Each clone is also shallow, because `_git_clone()` passes `--depth 1 --single-branch`, so its fetch configuration tracks exactly one branch.

## Decision

A clone is a read-only mirror of one remote branch. It is not a workspace. No person and no program may hold work inside it, and the remote is the only source of truth.

**Refresh resets; it never merges.** A refresh runs `git fetch`, then `git reset --hard`, then `git clean -fd`. It runs that same sequence every time, and it never first tests whether the working tree is clean. One path is easier to reason about than two, and a single path also covers a way of dirtying the tree that nobody has predicted yet.

**Refresh discards local changes without recording them.** A refresh keeps no copy, no patch, and no diff of what it discarded. The mirror rule above means a discarded change is never someone's work.

**Refresh pins the line-ending conversion off.** Every git command that writes the working tree passes `-c core.autocrlf=false`. The content on disk then matches the content in git, whatever the host operating system is, and whatever the host git configuration says. This follows the same reasoning as the existing `-c credential.helper=` argument: a refresh must not inherit a behaviour from the machine it happens to run on.

**The declared branch decides; a metadata file records what the clone actually holds.** Settings declare which branch a System wants. A `meta.json` file inside the clone directory records the branch, the commit, and the time of the last successful refresh. The declaration states intent, and the file states fact, so the two never merge into one value that can lie.

A refresh that finds the declared branch and the recorded branch to be different deletes the whole directory and clones again. A shallow clone tracks one branch only, so a fetch cannot reach a different one.

A refresh that finds no `meta.json` rebuilds it by asking git which branch the clone is on. It records the time as unknown. A missing file is not a reason to clone again, because `git clean -fd` deletes that file on every refresh and the refresh writes it back afterwards.

**A lock guards each clone directory.** The lock belongs to the directory, not to a System, because several Systems can share one directory. A refresh that finds the lock held reports that the mirror is busy and stops. It does not queue, because both callers would fetch the same content. A lock older than its timeout is treated as abandoned, and the next refresh takes it over.

The lock file sits beside the clone directory rather than inside it. `git clean -fd` would otherwise delete the lock in the middle of the refresh that holds it.

## Consequences

Any local change inside a clone disappears on the next refresh, silently. A person who wants to read, run, or debug one of these applications must clone the repository separately, somewhere else.

The two clones that Windows created repair themselves. The first refresh under this decision rewrites their working trees with line feeds, so `git status` reports them as clean from then on.

The pinned conversion changes what a Windows user sees inside a clone. Old Windows tools that cannot read a lone line feed will not display these files correctly. That cost is acceptable: a mirror is read by the analyzer, never edited by a person, and never committed back.

A future refresh cannot explain a discarded change, because nothing records one. Recovering that ability needs a new decision, not a new setting.
