# 01 — The glossary names the local copy of a repository

**What to build:** A maintainer reading `CONTEXT.md` finds a term for the local copy of a repository, and learns the rules that copy now carries: it mirrors one branch of one remote, it holds nobody's work, and a refresh replaces it whole. Today the glossary carries no such term, even though the concept governs how every refresh behaves.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `CONTEXT.md` carries one term for the local copy of a repository.
- [x] The entry states that the copy mirrors one branch of one remote.
- [x] The entry states that the copy holds no work, and that a refresh replaces it whole.
- [x] The entry states that one copy can serve several Systems.
- [x] The entry links to ADR-0023.
- [x] The entry names the synonyms to avoid, following the `_Avoid_` convention already in the file.

**Notes:** Added a new "Repository Management" section to `CONTEXT.md`, after "Web Application Analysis", with one term, **Clone**. The entry covers the mirror-of-one-branch rule, the no-work/whole-replacement rule, the one-clone-serves-several-Systems rule, and links to [ADR-0023](../../../docs/adr/0023-a-clone-is-a-read-only-mirror-reset-to-the-remote.md). `_Avoid_` lists: local copy, working copy, checkout, repo directory, workspace.
