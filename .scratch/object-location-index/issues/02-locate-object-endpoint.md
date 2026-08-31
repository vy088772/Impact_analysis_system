# 02 — `/locate_object` answers from the indexes alone

**What to build:** A caller asks one question — "which Databases could hold this name?" — and gets an answer without any SQL cache being opened. The caller sends an object name and a kind of `sp` or `table`; the kind selects which bucket to read, and therefore which name normalization applies.

The reply separates two different facts. `matched` names the Databases whose index is fresh and holds the name. `unindexed` names the Databases whose cache exists but whose index is absent by the staleness rule — the caller must read those in full, because the service cannot say. A Database with a fresh index that does not hold the name appears in neither list; that omission is the pruning, and it is authoritative.

Both lists name each Database by its full `(server, database)` identity, so a caller can match them against a Declared Database Dependency without resolving a bare name.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] The endpoint opens no SQL cache. A request that would require opening one is a bug, not a fallback.
- [ ] The endpoint reads every index on disk in one request, so one call answers for every System in the catalog.
- [ ] `matched` and `unindexed` are separate lists, each carrying full `(server, database)` identities.
- [ ] The reply reports how many indexes were consulted, so a caller can assert the cost.
- [ ] A missing, unreadable, or stale index puts its Database in `unindexed` — never in neither list, and never in `matched`.
- [ ] An unknown `kind` is rejected as a bad request rather than guessed.
- [ ] `/find_by_sp` and `/find_by_table` request and response shapes are unchanged, and their existing tests pass untouched.
- [ ] Behaviour is tested at the analysis-service seam, following the prior art that already drives the Reverse Lookup functions directly against a fixture cache directory. The route itself gets only the thin error-translation test its prior art uses.
- [ ] An ADR in this repo records the decision to treat a matching Object Location Index as authoritative and skip that cache unopened, and states why a stale index degrades to slow rather than wrong.
