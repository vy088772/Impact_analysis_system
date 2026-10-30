# 03: The Check Uses the Scan Account of Each Server

**What to build:** A server whose Database Registry entry names `uid_env` and `pwd_env` gets its SQL check with that account. The check reads the same account as a refresh of that server. No credential comes from an application Web.config (ADR-0010).

This ticket crosses two repositories. Impact_analysis_system accepts the accounts. `llamaindex-spec-rag` sends them.

See the spec: `.scratch/sql-cache-behind-source/spec.md` (section "Check" and section "`llamaindex-spec-rag` web side").

**Blocked by:** 02 (The Check Marks a Changed SQL Cache `behind_source`)

**Status:** ready-for-agent

- [ ] `POST /cache_freshness/check` takes an optional body with `sql_credentials`, keyed by server, with the same shape as in `/environment/check` and `/refresh_jobs/update_all`.
- [ ] A request with no body still works and uses the global account.
- [ ] The check passes the override of a server to the Fingerprint reader. A server with no override gets no override.
- [ ] In `llamaindex-spec-rag`, the client call for the check sends the scan account overrides from the Database Registry, the same as the "update all" call.
- [ ] An Impact HTTP API test with a fake reader shows that the reader gets the override of its server.
- [ ] A `llamaindex-spec-rag` test shows that the check request carries the overrides from the Database Registry.
