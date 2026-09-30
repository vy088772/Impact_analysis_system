# 08 — The documents record the rule

**What to build:** A maintainer opens the ADRs and the glossary and finds one rule, its sources, and its evidence. ADR-0037 records how an unstated schema resolves and what it reverses. ADR-0035 lists the three cases that still carry the Unproven Schema mark. `CONTEXT.md` defines Schema Resolution. The canonical-object-identity spec points to this spec where Step 2b is replaced.

See "Documents", "Further Notes", and user stories 42 to 48 in the spec.

**Blocked by:** 02, 03, 04, 05, 06, 07 (each document states behaviour the code must already have).

**Status:** done

- [x] ADR-0037 states the rule (the `sys` rule, the module's schema, then `dbo`), the Microsoft sources, the operator's confirmation, and the evidence from the seven caches.
- [x] ADR-0037 states what it reverses: the canonical-object-identity decision never to fill an unstated schema.
- [x] ADR-0037 states the assumptions: name comparison ignores case; dynamic SQL resolves against the login's default schema; the Microsoft text on a static `EXEC` is ambiguous, and this rule reads it as dynamic SQL only.
- [x] ADR-0035 gains an amendment that lists the three cases of the mark.
- [x] `CONTEXT.md` gains a Schema Resolution entry. The Canonical Object Identity and Unproven Schema entries agree with it.
- [x] The canonical-object-identity spec gains one line at its top that names this spec.
- [x] Every document fits STE100: one term per concept, description sentences of 25 words or fewer, paragraphs of six sentences or fewer.
- [x] Each behaviour claim is checked against the code before it is written.

**Notes:**
Files this ticket changed (other tickets run in parallel; these are the only ones):
- `docs/adr/0037-an-unstated-schema-resolves-as-sql-server-resolves-it.md` (new): the rule, sources, evidence, reversal, assumptions.
- `docs/adr/0035-an-unproven-schema-marks-one-execution-path.md`: one amendment at the end, with the three cases of the mark.
- `CONTEXT.md`: new Schema Resolution entry. Canonical Object Identity and Unproven Schema entries changed. "default schema" and "dbo fallback" left the Avoid list of Unproven Schema, because the default schema is now a SQL Server term that the rule uses.
- `.scratch/canonical-object-identity/spec.md`: one line under the Status line.
Checked against the code before writing:
- Step order: `schema_resolution.resolve()` checks the module schema, then `dbo`. `resolve_call()` adds `sys` last for `sp_` and `xp_`. The ADR states this order and says why `sys` last gives the same answer as `sys` first.
- Schema source values and the `module_schema` reading for a `dbo` module: ticket 04 notes and `schema_resolution.py`.
- SP Catalog reason: `SpCatalog.match_reason()`. A call with no schema hits `dbo.name`, else the bare bucket gives `unproven_schema`.
- Table match flag: `unproven_schema = not target_schema` in `service/table_match.py`.
- `db..name` keeps an empty schema also for the cache's own Database: `resolve()`.
Open points, not done here:
- Ticket 10 adds the `unproven_schema` flag to a `called_procedure_not_in_graph` path. The documents do not claim that flag. Re-read the Unproven Schema entry after ticket 10.
- ADR-0037 says the graph format version rises to 8. Ticket 09 makes the code do it (`GRAPH_VERSION` is still 7 now). The `tools/repair_sql_execution_graphs.py` docstring still says v7; ticket 09 owns it.
- No `/code-review` finding to record: only documents changed.
