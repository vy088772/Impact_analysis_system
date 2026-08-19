# 01 — A Declared Database Dependency Carries a Complete Database Identity

**What to build:** A System can state which Database it depends on when two Databases share a name on different servers. A System's catalog entry declares each dependency as a complete `{server, name}` pair instead of a bare name, so resolving a System's dependencies performs no registry lookup and cannot be ambiguous. Both the SQL scan command's System mode and the question-answering path read the declared pair directly.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A System's catalog entry declares each Declared Database Dependency as a `{server, name}` object; both keys are required and a System declaring nothing keeps an empty list.
- [x] The four Declared Database Dependencies that exist today (three on the `STC` System, one on `Y-Docs_TTPUR`) are migrated in place to the new shape, targeting the currently-registered server. No SQL cache is re-scanned, re-keyed, or otherwise touched.
- [x] Resolving a System's dependencies returns the declared pairs as declared, and consults the Database Registry for nothing.
- [x] The question-answering path's SQL cache source for a System comes from that System's first Declared Database Dependency, read directly. Taking the first entry remains the documented simplification; no `primary`/`owned` marker is introduced.
- [x] Given two servers each registering a Database named `PUR`, a System declaring the one on the first server resolves to that server every time, with no error and no prompt.
- [x] The by-name server lookup that returned a single first match is removed. It has no remaining caller after this ticket; ticket 03 introduces the replacement query when it has one.
- [x] The SQL scan command's existing System mode keeps working end to end, now sourced from the declared pairs. Its command-line shape is unchanged by this ticket — ticket 03 changes that.
- [x] The existing assertion that the shipped catalog declares dependencies as a list of name strings is **currently failing** — the shipped file gained a third entry the assertion was never updated for. It is rewritten against the new shape, not repaired against the old one.
- [x] Tests cover: dependencies parsed as pairs; the question-answering cache source read from the first pair with no registry access; a System declaring nothing; and the same-name-on-two-servers case resolving unambiguously.
