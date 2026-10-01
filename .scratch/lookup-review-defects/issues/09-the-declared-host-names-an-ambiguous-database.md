# 09 — The declared host names an ambiguous Database

**What to build:** Tickets 04 and 05 each left the question "who names the host?" to the other. The final review found that a Database on two hosts always came back as "name the host", and nothing could name it. The client now reads the catalog: when a lookup request for a declared Database gets `ambiguous_database`, the client sends the same request once more with the host that the System declares for that Database. The work is in the `llamaindex-spec-rag` repository. The server does not change.

**Blocked by:** None — tickets 04 and 05 are done.

**Status:** done (branch lookup-review-followup in llamaindex-spec-rag, commit 79528ea)

- [x] The first request of a reverse lookup carries no host, as before. A System with no same-name Database sees the same requests as before.
- [x] On `ambiguous_database`, the client sends the request again with the declared host of that Database. One retry per Database.
- [x] A read with the declared host is a normal read. It does not enter `databases_skipped`.
- [x] A Database with no declared host, or a retry that still fails with the same code, enters `databases_skipped` with the reason "several hosts", as in ticket 04.
- [x] An explicit `db_server` from the caller still wins over the declared host.
- [x] An unknown 409 code still raises.

## Note (implementation)

- `impact_orch/rag_client.py`, `_lookup_outcomes`: in the reverse-lookup mode (`skip_ambiguous_database`), the first `build_payload(name, "")` sends no host. On `ambiguous_database` and a non-empty declared server it calls `build_payload(name, declared_server)` once. The two lookup closures send `db_server or declared_server`. `/analyze` and `/flow_chain` do not use this mode and do not change.
- Cost: one extra request, drawn from the run budget (ticket 01), only for an ambiguous Database.
- Why a retry and not "always send the declared host": a declared host that differs from the stored cache host (an alias, a domain suffix) would turn a working lookup into "not scanned". The retry runs only where the lookup already fails.
- Tests: `DeclaredHostRetryTests` in `tests/test_lookup_db_server.py` (retry with the declared host for both lookups, no retry without a declared host, no host on the first request).

## Note (the review after the final check)

Decisions about the findings of the two-axis check of the whole spec:

- Standards, fixed: the repeated `except` tuple is one constant (`api.py`); `get_path_evidence` filters on `req.program_names`, not on an empty list; the `read_through` comment is short with the detail below; `_database_unreads` uses ordered lists; a guard test keeps the three unread-reason tables in step; `CONTEXT.md` of the client has an **Unread System** entry.
- Standards, kept on purpose: the two Boolean flags of `_lookup_outcomes` (each has its own test, and `/analyze` uses neither); `request_budget` passed through three layers (the cost of ticket 01); the one-field base class `LookupDatabaseHost` (two request models share it).
- Spec, fixed: story 12 end to end (this ticket). Story 6: an unfinalized answer also shows its report path when one exists; its heading stays "analyzed no code". Ticket 06: the server commit `950a98e` and the client commit `d0caca2` are separate commits.
- Scope that goes beyond the spec, kept and now recorded: `servers` in the 409 body (ticket 05; it tells the person which hosts to choose from); the `ambiguous_database` check ahead of the `cache_only` skip (the Database fact does not depend on the repo); partial reads at the ceiling (ticket 01 review); the CONTEXT.md entries. `read_through`, `_inline_match_rank` and the C# parser changes in the same diff belong to tickets 09 and 10 of other efforts, not to this spec.
