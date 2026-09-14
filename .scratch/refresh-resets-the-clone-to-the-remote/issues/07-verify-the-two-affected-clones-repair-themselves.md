# 07 — The two damaged clones repair themselves on their first refresh

**What to build:** A maintainer refreshes the two Systems that could not refresh, and both succeed with no manual git command. The `Y-DOCs` clone held 1521 modified files and the `STC` clone held 60, all of them line-ending differences left by a clone created on Windows and moved to macOS. The decision was to repair them through the new refresh path rather than by hand, so this ticket is that decision's proof.

**Blocked by:** 03, 05, 06

**Status:** ready-for-agent

- [ ] A refresh of the `Y-Docs_TTPUR` System succeeds.
- [ ] The `Y-DOCs` clone reports a clean working tree afterwards.
- [ ] The `STC` clone reports a clean working tree after its own System refreshes.
- [ ] Both clones' `meta.json` records a branch, a commit, and a real time.
- [ ] Nobody ran a git command against either clone by hand.
- [ ] A second refresh of either System also succeeds, and leaves the working tree clean.
