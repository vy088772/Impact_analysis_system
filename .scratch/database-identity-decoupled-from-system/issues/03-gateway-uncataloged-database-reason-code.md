# 03 — Gateway Distinguishes "Uncataloged Database" From "Connection Unresolved"

**Repo:** `Impact_analysis_system`
**Spec:** `.scratch/database-identity-decoupled-from-system/spec.md`

**What to build:** With ticket 01's resolver now returning a real `{server, database}` and ticket 02's cache now keyed by that pair, wire them together so `CSharpAnalysisGateway` reports the correct reason. This closes the original bug: `Global.asax.cs`'s `spAddRecordError` call must report `not_in_resolved_catalog` (database known, not yet scanned) instead of `connection_source_unresolved` (database unknown).

**Blocked by:** 01 (needs resolved `{server, database}`), 02 (needs the new cache-key format to check catalog membership against)

**Status:** done

- [x] `_resolve_database()` in `csharp_analysis_gateway.py` returns the resolved server alongside the database.
- [x] `DbInvocation.server` is populated end-to-end for a resolved connection.
- [x] Running analysis against `STC/Global.asax.cs`'s `WriteDB`/`spAddRecordError` call produces `evidence=UNRESOLVED`, `reason=not_in_resolved_catalog`, `database=SysErrorRecord` (not `connection_source_unresolved`, not `database="ERROR"`).
- [x] A connection that genuinely cannot be resolved to any database still produces `connection_source_unresolved`/`ambiguous_connection_source` exactly as before — this ticket does not change behavior for that case.
- [x] `_rate_literal_candidate()`'s existing branch logic is confirmed unchanged (it already does the right thing) — this ticket only fixes what feeds it.
- [x] `tests/test_csharp_analysis_gateway.py` gains a case built via the existing `CSharpAnalysisGateway(catalog, connection_sources=...)` pattern that reproduces the `spAddRecordError` scenario: a resolved-but-uncataloged `(server, database)` pair must produce `not_in_resolved_catalog`.

## Comments

Tickets 01 and 02 already delivered the first two boxes: `_resolve_database()` returns
`(database, server)` and every `DbInvocation` construction site threads `server` through.
`_rate_literal_candidate()` is untouched -- it already reported `not_in_resolved_catalog`
whenever a resolved database missed the loaded catalog.

Two things still stood between that and the `spAddRecordError` case, both outside the
gateway. Neither is named by a checkbox; both are load-bearing for box 3, and a reviewer
reasonably reads them as exceeding the ticket.

1. **The analyzer host dropped the wrapper's own connection.** `WriteDB` takes no
   connection from its caller -- it declares `cn` itself -- so
   `ResolveCallConnectionExpression` bailed out and the call site reported no connection
   source at all. `WrapperDefinition` now records `DeclaresConnectionAsLocal` and
   `SourceFilePath` and answers `SuppliesConnectionTo(callFilePath)`; a call site inherits
   the connection expression of a wrapper that owns its connection and is declared in the
   calling file. The same-file guard matters: `connection_sources` is keyed per file, so a
   variable name means nothing outside it. A wrapper handed its connection by a caller is
   unaffected.

2. **`analyze_service` overwrote the resolved database.** `_execution_connection_sources()`
   remapped every entry onto the selected graph scope whenever a file held one distinct
   label, which rewrote `SysErrorRecord` to `STC`. That rule predates ticket 01, when a
   label was a system_id carrying no evidence. A resolved `{server, database}` entry is
   now authoritative and is only rewritten when its name is an alias of the selected scope;
   the lone-label convenience still applies to legacy plain-string entries. That alias test
   matches on database name alone, not on ADR-0009's `(server, database, schema)` identity,
   because the selected scope reaches this function as a bare name -- pre-existing, now
   stated in a comment rather than implied.

Verified against the real source (`data/repos/System_Dept_1/STC/STC/Global.asax.cs`,
scan + `_execution_connection_sources` + gateway, cache scope `STC`):

    connection_sources: {'cn': {'database': 'SysErrorRecord', 'server': 'vmsystest07'}}
    evidence=unresolved reason='not_in_resolved_catalog'
    database='SysErrorRecord' server='vmsystest07'

`data/` is gitignored, so that run is not a committed test. The committed coverage
reproduces the same shape through the real analyzer host in a temp file.

**Box 4 needed a fix that review caught.** Inheriting the wrapper's connection first
regressed the case it protects: when the inherited variable resolves to no database (the
connection is built from a literal or a runtime value, so the tracker never records it),
the call site went from `connection_source_unresolved` to a `LIKELY`/`unique_across_catalogs`
guess -- the exact guessing this spec exists to stop. The inherited expression is now also
reported as the call site's single connection candidate, which `_rate_literal_candidate()`
already reads as `connection_source_unresolved` when nothing resolves, and ignores when
something does. `test_unresolvable_wrapper_owned_connection_stays_connection_source_unresolved`
locks this down; the pre-existing
`test_explicit_null_connection_source_stays_unresolved_even_when_catalog_is_unique` and
`test_multiple_connection_candidates_stay_unresolved_when_catalog_is_unique` still pass.

Follow-up for `/domain-modeling`, not done here: the pivot of this change -- a resolved
`{server, database}` connection source versus a legacy label -- has no `CONTEXT.md` term
and travels as `Any` through three helpers.

Full suite: 484 passed, 11 failed -- the same 11 that fail on `HEAD` before this change
(external wrapper contracts, MVC scan, formal output migration), plus
`test_search_roles.py`/`test_sp_tables.py`, which cannot collect without an ODBC driver.
