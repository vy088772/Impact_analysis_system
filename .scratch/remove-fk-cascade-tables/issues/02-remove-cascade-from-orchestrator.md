# 02 — Remove the FK cascade table from the orchestrator

**What to build:** The orchestrator no longer asks for a FK cascade table, and
no longer reads one. An analyst who runs the command line sees the outline, the
stored procedures and the real tables, with no cascade table line. The prompt
for the AI and the prompt for the agent hold the same three facts and no cascade
line.

The grounding step no longer adds cascade table names to its allowlist. The
allowlist is the set of names that the hallucination check accepts as real. A
master table used to add up to 50 unrelated names to that set, which let an
invented answer pass. After this ticket the check rejects a table name that the
program does not touch.

The orchestrator removes the cascade depth setting and the matching entry from
the environment file. The environment file comment says today that the resolver
queries the database when the cache is absent. That statement is wrong, because
ADR-0011 removed that query. Remove the comment with the entry.

The merge step unions two fields across caches today. After this ticket it
unions the stored procedure names only. The forward chain merge loses the
cascade key for the same reason.

**Blocked by:** None — can start immediately. This ticket does not gate ticket
01, and ticket 01 does not gate this one. The service ignores an unknown request
field, and every consumer reads the response field with a safe default.

**Status:** done

- [x] The command line output holds no cascade table line.
- [x] The prompt for the AI holds no cascade table line.
- [x] The prompt for the agent holds no cascade table line.
- [x] The grounding allowlist holds only the tables that the program really reads or writes.
- [x] The orchestrator sends no cascade depth to either endpoint.
- [x] The configuration and the environment file declare no cascade depth.
- [x] The merge step unions the stored procedure names only.
- [x] The two tests that used the cascade field as a cache marker use the stored procedure names instead, and keep their coverage.
- [x] The whole test suite of this repository passes.

**Note (2026-09-22):** Repository is `llamaindex-spec-rag`, not this one
(the spec's companion repo). Removed `fk_depth` from `rag_client.analyze()`
and `rag_client.flow_chain()` (parameter, docstrings, and the payload dict
key sent to `/analyze` and `/flow_chain`), the `IMPACT_FK_DEPTH` setting
from `config.py`, and its `.env` entry plus the three-line comment above it
(the comment claimed a live `sys.foreign_keys` query fallback, which
ADR-0011 had already removed). Removed the five read sites: the "FK 連動表"
line in `run_cli.py`, the "外鍵連動資料表" line in `context_builder.py`
(prompt for the AI), the "FK 連動資料表" line in `agent_tools.py`'s
`_render_forward_chain` (prompt for the agent), `related_tables` from the
grounding allowlist build in `grounding.py`, and `related_tables` /
`related_tables_fk` from the two union-field lists in `analyze_merge.py`
(`_UNION_FIELDS`) and `rag_client.py` (`_FORWARD_CHAIN_UNION_KEYS`).

Found no other call sites passing `fk_depth=` explicitly, so dropping the
parameter is not a breaking change to any caller in this repo.

Two test files build a program payload with the cascade field:
`tests/test_analyze_declared_databases.py` and
`tests/test_transient_retrieval_retry.py`. Removed the field from every
fixture in both. Only one assertion used it as a cache-identity marker
(`test_transaction_app_reports_eight_stored_procedures_and_proven_paths`,
`assert program["related_tables"] == ["STCMaster"]`) — replaced it with
`assert program["stored_procedures"] == [...]` against the exact SP name
list (not just the existing length check two lines above), so the test
still pins down which cache's data won the merge. The retry test's two
occurrences were both empty-list fixture noise with no assertion on them,
so those were a plain deletion.

Full suite: `.venv/bin/python -m pytest` — 1129 passed, 2 failed. Confirmed
the same 2 failures exist on `git stash` (pre-change code), same error
messages (`test_path_evidence_wiring.py::test_clients_route_the_sql_cache_by_database_name_not_system_id`
raises `KeyError: 'database'`; `test_source_resolver_databases.py::test_the_shipped_catalog_declares_databases_as_full_identities`
has a mismatched catalog fixture) — both are shipped-catalog/routing issues
unrelated to the cascade field. This change adds zero new failures.

Note for whoever picks up ticket 04: this repo's `.env.example` never had
an `IMPACT_FK_DEPTH` entry to begin with, so there is nothing to remove
there; only `.env` had it.
