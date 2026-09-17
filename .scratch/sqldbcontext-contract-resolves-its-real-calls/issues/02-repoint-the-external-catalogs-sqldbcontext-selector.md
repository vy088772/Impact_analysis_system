# 02 — Repoint the external catalog's sqldbcontext selector to the new Contract

**What to build:** Every System in the external system catalog that currently
selects `sqldbcontext` by name is repointed to the new registry entry ticket
01 produced, so a future refresh actually reaches the fixed Contract instead
of the stale one. The blast radius is checked directly against the catalog,
not assumed from the receiver-type name alone — a same-named receiver in a
different System could carry a different Contract Fingerprint entirely.

**Blocked by:** 01 — Re-decompile and accept sqldbcontext against its real
parameter types (the new entry's name is only known once that ticket lands).

**Status:** ready-for-agent

- [ ] The external system catalog is checked directly for every System whose
      `wrapper_contract` names `sqldbcontext` today.
- [ ] Each System found there (today expected to be IQCS alone) has its
      `wrapper_contract` field repointed to the new entry's name.
- [ ] No other field on that System's entry, and no other System's entry, is
      touched.
- [ ] The edit is made in the catalog repository's working tree only; the
      commit there is left to that repository's own owner, since this
      repository does not own it.
