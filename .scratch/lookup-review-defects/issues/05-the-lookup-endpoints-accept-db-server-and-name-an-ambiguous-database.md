# 05 — The lookup endpoints accept the Database host and name an ambiguous Database

**What to build:** `/find_by_sp` and `/find_by_table` accept an optional `db_server`, as `/path_evidence` and `/flow_chain` already do. The server resolves the one SQL cache from that host. A Database name that lives on more than one host, with no host named, gets the new error code `ambiguous_database`. A Database that is not scanned keeps the code for "not scanned". See the SQL Cache Identity entry in `CONTEXT.md` and ADR-0033. The work is in this repository, and it ships after ticket 04.

**Blocked by:** 04 — The client sends the Database host and reads "several hosts" as its own reason

**Status:** ready-for-agent

- [ ] Both request schemas gain an optional `db_server`.
- [ ] The server passes `db_server` to the same cache-identity resolution that the other endpoints use.
- [ ] A test at the HTTP API shows the new code for a Database on two hosts with no host named.
- [ ] A test shows a correct answer when `db_server` names one of the two hosts.
- [ ] A test shows the old code for a Database that is not scanned.
- [ ] A call without `db_server` for a Database on one host keeps today's behavior.
