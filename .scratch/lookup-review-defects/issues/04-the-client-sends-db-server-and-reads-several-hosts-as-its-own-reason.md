# 04 — The client sends the Database host and reads "several hosts" as its own reason

**What to build:** The client of the two lookup endpoints sends the Database host (`db_server`). It also knows a new error code, `ambiguous_database`, and reports it as its own unread reason: the Database exists on several hosts, name the host. The person no longer reads that case as "not scanned". The client ships before the server (see ticket 05). An old server ignores the optional field, so the client is safe alone. The work is in the `llamaindex-spec-rag` repository.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Both lookup requests carry `db_server` when the caller names one.
- [ ] The new code maps to a new unread reason that tells the person to name the host.
- [ ] The existing code for "not scanned" still maps to "not scanned".
- [ ] A 409 with an unknown code still raises. It never turns into a skip.
- [ ] A test at the cross-system lookup entry covers the several-hosts case and the not-scanned case.
- [ ] A lookup without `db_server` keeps today's behavior.
