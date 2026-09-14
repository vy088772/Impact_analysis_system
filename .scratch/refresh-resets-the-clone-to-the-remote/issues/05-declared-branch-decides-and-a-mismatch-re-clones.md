# 05 — Changing the declared branch moves the clone to it

**What to build:** A maintainer changes the branch a System declares, runs a refresh, and gets a clone on the new branch. Today a clone tracks exactly one branch, because it is created shallow and single-branch, so fetching a different branch is not available to it. The refresh therefore deletes the whole directory and clones again.

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] A refresh reads the declared branch from settings and the catalog.
- [ ] A refresh whose declared branch equals the recorded branch fetches and resets as usual.
- [ ] A refresh whose declared branch differs from the recorded branch deletes the whole clone directory.
- [ ] That refresh then clones the declared branch.
- [ ] The new clone records the declared branch in `meta.json`.
- [ ] A missing `meta.json` still does not count as a mismatch.
