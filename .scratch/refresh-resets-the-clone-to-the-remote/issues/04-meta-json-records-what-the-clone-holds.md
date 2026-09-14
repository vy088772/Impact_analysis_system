# 04 — The clone records which branch, which commit, and when

**What to build:** A maintainer opens a file in the clone directory and reads the clone's state without running git: which branch it holds, which commit it stopped at, and when it last refreshed successfully. Settings declare which branch a System wants; this file records what the clone actually holds. The declaration states intent and the file states fact, so neither value can quietly stand in for the other.

Losing the file costs nothing. The cleaning step deletes it on every refresh, and the refresh writes it back.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] A successful refresh writes `meta.json` inside the clone directory.
- [ ] The file records the branch, the commit, and the time of the last successful refresh.
- [ ] The time field holds an explicit unknown value when the time is unknown.
- [ ] That unknown value is distinct from a real time, and distinct from a missing field.
- [ ] A refresh that finds no `meta.json` asks git which branch the clone holds, and rebuilds the file.
- [ ] A rebuilt file records the time as unknown.
- [ ] A missing `meta.json` never triggers a fresh clone.
- [ ] A first-time clone writes `meta.json` immediately.
