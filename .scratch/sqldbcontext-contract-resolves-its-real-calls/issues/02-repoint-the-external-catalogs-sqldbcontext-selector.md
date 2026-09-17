# 02 — Repoint the external catalog's sqldbcontext selector to the new Contract

**What to build:** Every System in the external system catalog that currently
selects `sqldbcontext` by name is repointed to the new registry entry ticket
01 produced, so a future refresh actually reaches the fixed Contract instead
of the stale one. The blast radius is checked directly against the catalog,
not assumed from the receiver-type name alone — a same-named receiver in a
different System could carry a different Contract Fingerprint entirely.

**Blocked by:** 01 — Re-decompile and accept sqldbcontext against its real
parameter types (the new entry's name is only known once that ticket lands).

**Status:** done

- [x] The external system catalog is checked directly for every System whose
      `wrapper_contract` names `sqldbcontext` today.
- [x] Each System found there (today expected to be IQCS alone) has its
      `wrapper_contract` field repointed to the new entry's name.
- [x] No other field on that System's entry, and no other System's entry, is
      touched.
- [x] The edit is made in the catalog repository's working tree only; the
      commit there is left to that repository's own owner, since this
      repository does not own it.

## Note (implementation)

**The check.** Searched `llamaindex-spec-rag/catalog/system_catalog.json`
(case-insensitive, whole file) for `sqldbcontext`. One match:
`system_id: "IQCS"`, `wrapper_contract: "sqldbcontext"`, line 863. No other
System entry names it, so IQCS alone was in scope — matching ticket 01's
expectation, but confirmed against the catalog itself, not assumed.

**The edit.** `wrapper_contract` on the IQCS entry changed from
`"sqldbcontext"` to `"sqldbcontext-53e5d16df832"` (ticket 01's new registry
entry). `git diff` in `llamaindex-spec-rag` shows exactly one changed line,
one field, one System entry — nothing else in the file touched.

**Left uncommitted.** The edit sits in `llamaindex-spec-rag`'s working tree.
That repository is not owned here, so no commit was made there; its own owner
commits it.
