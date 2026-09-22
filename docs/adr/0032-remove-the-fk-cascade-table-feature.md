# Remove the FK Cascade Table Feature

**Status:** Accepted
**Date:** 2026-09-22

## Context

The analysis service reported a "FK cascade table" for each program: a table that `service/fk_resolver.py` judged related to a table the program reads or writes. The resolver did not read a foreign key constraint. It read the SQL cache and inferred a relation from the name of a primary key.

The SQL cache holds no foreign key data. A cached table object holds three fields only: the name, the columns, and the primary keys. A primary key does not describe a relation. A primary key states that a column identifies a row in its own table. It names no other table. A foreign key names the other table. The databases this project analyzes declare primary keys only, so the inference had no structural base to build on.

The primary key coverage the inference could reach was partial. The PUR database holds 401 tables. 216 tables have a primary key, and 128 tables have a single primary key — the resolver skipped a compound primary key, so 32 percent of PUR's tables could start an inference. The other databases measured 72 percent, 32 percent, 100 percent, and 0 percent primary key coverage.

The inference failed on a master table, which is where a user needs a correct answer most. The PUR adjacency built from this coverage has 247 nodes and 346 edges. The largest fan-out is 65, at the `Customers` table. A depth of 1 from `Customers` returns 50 tables, which is the resolver's cap. A depth of 2 returns the same 50 tables — the walk cannot get past the cap once it hits it. The `Quotation` table returns 33 tables at depth 1 and also hits the cap at depth 2.

A filter did not rescue the inference. A filter that removed the temporary tables, the work tables, the backup tables, the log tables, and the system tables gave this result for the three largest master tables: `Customers` returns 0 tables, `Vendors` returns 0 tables, `Quotation` returns 0 tables. The same filter gave 5 tables for `PQRMaster` and 4 tables for `BudgetHeader`, both detail tables. The signal ran inverse to the need — the filter thinned the master tables to nothing and left the detail tables with a few results nobody needed, since a detail table's own result carries little information: `PQRMaster` mostly returns its own detail tables, which a reader already gets from the table name prefix.

These measurements come from a probe that called the real adjacency builder and the real breadth-first search in `fk_resolver.py`, against the live SQL caches in `data/sql_cache/`, before the resolver was removed.

The feature also damaged the answer it was meant to support. The grounding step's hallucination check builds an allowlist of table names it accepts as real. For a master table, the resolver added up to 50 unrelated names to that allowlist, so the check would accept any of those 50 names in an AI-written answer even though the program never touched them.

## Decision

The primary key naming inference is not sufficient for a cascade table report. The feature is removed.

The analysis service (`Impact_analysis_system`) removed `service/fk_resolver.py` and its dedicated test file, the cascade depth field from both request schemas, and the cascade table field from both response schemas. The orchestrator (`llamaindex-spec-rag`) removed the cascade depth setting, the matching environment file entry, the cascade line from the command-line output and from both the AI and agent prompts, the cascade names from the grounding allowlist, and the cascade key from both merge steps' union lists.

This ADR supersedes design decision 9 in `docs/INTEGRATION_DESIGN.md` §10 ("FK 連動深度：預設 1 層", "FK cascade depth: default 1 level"), which set the default cascade depth to 1. That decision recorded an earlier position; this ADR is the current one.

## Consequences

- An analyst gets the program outline, the source code, and the stored procedures the program really calls — no cascade table field, and no depth parameter to configure. This is a breaking change to the API contract of the `/analyze` and `/flow_chain` endpoints; no caller outside these two repositories read the removed field.
- The hallucination check's allowlist no longer carries up to 50 unrelated table names per master table. It now rejects a table name the program does not touch, which was not reliably true before this decision.
- **Known gap, unchanged by this decision:** the scanner still does not collect actual foreign key constraints, and the SQL cache still has no field for them. [ADR-0011](0011-remove-live-query-fallbacks.md) already recorded this gap and left real FK support out of scope; this decision does not narrow or widen that scope. It removes the one signal — PK-naming inference — that ADR-0011 kept as this project's only FK-adjacent evidence, because the measurements above show that signal does not hold up as a cascade table report. Real FK support, if ever wanted, needs a scanner change, a new cache refresh, a resolver that reads real foreign keys, and a database administrator who declares real foreign key constraints — none of which this decision does.
- [ADR-0011](0011-remove-live-query-fallbacks.md) keeps its original text, and its Decision section still cites `fk_resolver.resolve_fk_related()` as evidence that a live-query fallback in that function could not run. That function no longer exists — `fk_resolver.py` is gone as of this decision. A reader of ADR-0011 who checks that citation today will not find the function; this note is the record of why.
- Design decision 9 in `docs/INTEGRATION_DESIGN.md` §10 keeps its original text, and so does the S3 milestone row in §9, which names `fk_resolver.py` as what the team built at that stage. Both are historical records of an earlier position and an earlier build, not descriptions of the current system. A reader who wants the current position on FK cascade tables finds it here.
