# 02 — Document not_applicable and record ADR-0007

**What to build:** `CONTEXT.md`'s Evidence Status definition documents `not_applicable` as a legitimate fourth value (the code already assigns it; the glossary currently omits it). A new ADR, `docs/adr/0007-*.md`, records that this service's Evidence Status and `llamaindex-spec-rag`'s identically-named Evidence Status are two distinct concepts that happen to share a name — a per-Database-Invocation confidence rating here, versus a per-path/query conclusion there — so a future contributor or architecture review doesn't conflate them.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `CONTEXT.md`'s Evidence Status entry lists `proven`/`likely`/`unresolved`/`not_applicable` as the full value set
- [x] `docs/adr/0007-*.md` exists, follows the numbering and format convention of `0001`–`0006`
- [x] The ADR explicitly names both repos' Evidence Status concepts and states they are unrelated despite the shared name

`docs/adr/0007-evidence-status-name-collision-with-llamaindex-spec-rag.md` created. `CONTEXT.md`'s Evidence Status entry now lists all four values and links to the ADR. Ticket 08 (the reciprocal note in `llamaindex-spec-rag`'s `CONTEXT.md`) is unblocked but out of scope for this ticket — it lives in the other repo.
