# 08 — Note the Evidence Status name collision in llamaindex-spec-rag's CONTEXT.md

**What to build:** `llamaindex-spec-rag`'s `CONTEXT.md` gets a note on its own Evidence Status entry stating that it is a distinct concept from this service's identically-named Evidence Status, referencing ADR-0007 rather than duplicating its explanation — so a future contributor reading both glossaries side by side isn't misled by the name collision.

**Blocked by:** 02 — the ADR it references must exist first.

**Status:** done

- [x] `llamaindex-spec-rag`'s `CONTEXT.md` Evidence Status entry notes it is unrelated to `Impact_analysis_system`'s identically-named concept
- [x] The note references ADR-0007 by number/link instead of re-explaining the distinction inline
