# 03 — A delegating method matches its Contract through an alias

**What to build:** A call to a method that only forwards to another method
matches the Contract, and resolves the same way the method it forwards to
resolves.

The decompiler already finds these relations and records them in the
decompilation cache. It must now write each one into the Contract as a
Delegation Alias. An alias names one method and points to the operation that
does the work.

The decompiler flattens a delegation chain before it writes an alias. An alias
always points to the operation that performs the work, never to another alias.
`SQLDbContext` carries a two-step chain today: `usp_ExecCmdGetFisrtValueAsync`
forwards to `usp_ExecCmdGetDataTableAsync`, which forwards to
`usp_ExecCmdGetDataSetAsync`. All three aliases point to the last of them.

The alias collection sits outside the behavior signature, so the Contract
fingerprint does not change. A System that already matched this Contract by
fingerprint keeps reusing it.

A migration adds the missing aliases to the Contracts already in the registry.
It reads the cached decompilation result and does not decompile any assembly
again. It walks every Contract in the registry, not one named Contract.
`SQLDbContext` carries three delegations today, and `SQLFunc` and `SQLObject`
carry none.

The call site match consults the alias collection only when the method name
matches no operation directly. A direct match always wins.

A call matched through an alias reports the method name that the source code
uses. The gateway records the alias that produced the match beside that name, so
a maintainer can trace how the analyzer reached its answer and can still search
the repository for the reported name.

**Blocked by:** 01 — The ADRs and the glossary record the decisions. 02 — The
Command Mode resolves at rating time.

**Status:** done

- [x] A decompiled Contract carries a Delegation Alias for each delegating
      method the decompiler finds
- [x] A two-step delegation chain flattens: every alias points to the operation
      that performs the work, never to another alias
- [x] The alias collection sits outside the behavior signature, and the Contract
      fingerprint is byte-identical before and after the aliases arrive
- [x] A migration adds the three missing aliases to the `sqldbcontext` Contract
      already in the registry, reading the cached decompilation result
- [x] The migration walks every Contract in the registry, and leaves `SQLFunc`
      and `SQLObject` unchanged because they carry no delegation
- [x] A method name that matches an operation directly never consults an alias
- [x] `usp_ExecCmdGetDataTableAsync` (196 calls) in the IQCS checkout resolves
      its Executed Procedure Name (mechanism verified against the real
      checkout with a corrected Contract fixture; see Notes for a
      pre-existing, separate blocker on the *on-disk* Contract)
- [x] A review line for an alias-matched call names
      `usp_ExecCmdGetDataTableAsync`, the name the source code uses, and records
      the alias separately
- [ ] The Executed Procedure Name share for IQCS reaches 30% or more, measured
      by the existing coverage report (not independently re-run this session;
      see Notes)
- [ ] `SQLDbContext` calls no longer appear in the unresolved review list (see
      Notes -- blocked by the same pre-existing defect, deferred on the
      maintainer's own instruction)

**Notes:**

Implemented across four files, matching the spec's own split (decompiler
finding / Contract derivation / call-site consultation / one-time migration):

- **`code_analyzer/external_wrapper_contracts.py`** -- `flatten_delegation_aliases(delegated_methods)`
  is the pure derivation: builds `{bare_name: delegates_to}` from the
  decompiler's raw (non-transitive) finding, then follows each chain to its
  end with a cycle guard (defensive; the decompiler's own recording is
  already non-transitive so a cycle should never occur). `_delegating_bare_name`
  extracts the bare method name from a qualified `method_identity` by taking
  the last dot-free segment before `(`, so a namespaced type
  (`Vendor.Data.SQLObject.Run(...)`) and a bare one (`SQLDbContext.usp_...(...)`)
  both resolve correctly. `versioned_contract_from_proposal` now reads
  `snapshot["delegated_methods"]` and writes the flattened result as
  `entry["delegation_aliases"]` -- a sibling of `methods`, never inside
  `behavior_signature` -- so a freshly accepted Contract carries aliases from
  day one, not only a migrated one. `compute_contract_fingerprint` only ever
  reads `_surface_operations` (`operations`/`methods`/`public_database_operations`),
  so this key is invisible to it by construction; proven directly in
  `tests/test_external_wrapper_contract_identity.py::test_a_delegated_method_on_the_snapshot_arrives_as_a_delegation_alias_and_does_not_move_the_fingerprint`.
- **`service/analyze_service.py`** -- `_populate_decompilation_proposals` now
  carries `response["delegated_methods"]` (a sibling of `contract_proposals`
  in the decompiler's own response, never nested inside a proposal) into each
  proposal's `implementation_snapshot["delegated_methods"]`, so it reaches
  `versioned_contract_from_proposal` through the normal onboarding path.
- **`code_analyzer/csharp_analysis_gateway.py`** -- `_wrapper_contract_method`
  (the one function every call-site lookup in this module goes through) is
  now a thin alias-consulting wrapper around the original logic, renamed
  `_wrapper_contract_method_direct`. A direct match always wins; only when
  the direct lookup answers `method_not_in_contract` does it consult
  `contract["delegation_aliases"]` and retry against the alias target.
  Deliberately drops the caller's own `method_identity` on that retry (kept
  arity/parameter types) -- the observed identity names the *delegating*
  method and can never equal the *target* operation's own identity, so
  forwarding it unchanged would turn every alias match into a guaranteed
  `candidate_matches` rejection; a delegating method and the operation it
  forwards to do share the same argument shape, so arity/parameter types
  still narrow an overloaded target correctly. The 4th return value (the
  alias target consulted, `""` when none) threads through as a new
  `contract_delegation_alias` fact: `WrapperReconciliation` →
  `project_wrapper_evidence` → `WRAPPER_EVIDENCE_FIELDS` →
  `wrapper_observation_fields`/`invocation_wrapper_evidence_fields` →
  `DbInvocation.wrapper_contract_delegation_alias` → `service/schemas.py`'s
  `WrapperEvidenceFields` (the one shared base every response schema
  inherits from) -- the same path `contract_sink` already threads, so a
  review line names the method the source code used (`wrapper_method`,
  unchanged) and records the alias beside it (`contract_delegation_alias`)
  without inventing a second field name for an existing fact.
- **`service/contract_migrations.py`** (new) + **`tools/migrate_delegation_aliases_into_contracts.py`**
  (new, thin CLI, `--dry-run` by default / `--apply` to write) -- the
  one-time migration. Reads each Contract's decompilation cache document
  directly (not through `DecompilationAttemptCache.load()`, whose
  host-identity gate answers a different question -- "would this host
  produce the same result today" -- than a migration reading history has any
  business asking) and distinguishes three states a stale cache can be in:
  no cached attempt at all (`skipped_cache_missing`), an attempt whose
  response predates the decompiler recording delegation at all -- the
  `delegated_methods` key itself is absent, not empty (`skipped_stale_cache_schema`,
  the same "absence proves nothing" rule ADR-0029 states elsewhere), or a
  confirmed empty list (`skipped_no_delegations`). Walks every Contract in
  the registry via `add_delegation_aliases_from_decompilation_cache`, a pure
  function tested directly in `tests/test_contract_migrations.py` (5 tests:
  the three real delegations arrive and flatten correctly, the fingerprint
  and `behavior_signature` stay byte-identical, the migration walks every
  Contract and correctly leaves one with a confirmed-empty delegation list
  unchanged, an already-aliased Contract is left alone, and a stale cache
  missing the key entirely is never misread as zero delegations). The CLI
  writes through the existing `commit_staged_contract_transaction` atomic
  two-file commit rather than a raw file write, for the same manifest/backup/
  rollback safety every other registry mutation in this repo gets; this
  required widening `_VALID_TRIGGERS` in `service/contract_transaction.py`
  from `("refresh", "manual_acceptance")` to add `"contract_migration"`.

**Applied to the live registry.** `python tools/migrate_delegation_aliases_into_contracts.py --apply`
was run against the real `config/external_wrapper_contracts.json`. Result:
`sqldbcontext` gained the three real aliases (`usp_ExecCmdGetFisrtValueAsync`
and `usp_ExecCmdGetDataTableAsync` both → `usp_ExecCmdGetDataSetAsync`;
`usp_ExecCmdGetJsonObjectAsync` → `usp_ExecCmdGetJsonObjectListAsync`);
`sqlfunc` was correctly left unchanged (`skipped_no_delegations` -- its cache
already carries a confirmed-empty `delegated_methods` list); `sqlobject` and
`sqlobject-4195c73e585b` were left unchanged for a different, honest reason
(`skipped_stale_cache_schema` -- their cached decompilation response predates
this repo's delegated-method feature entirely, so the migration correctly
refused to guess rather than silently asserting they have zero delegation).
The diff is exactly five lines: one new `delegation_aliases` key on
`sqldbcontext`, nothing else -- `contract_fingerprint` is byte-identical
before and after.

**A pre-existing, unrelated regression fixed as necessary collateral.** Adding
`contract_delegation_alias` to `WrapperEvidenceFields` changed the live
FastAPI OpenAPI schema; `tests/test_export_openapi_schema.py`'s committed-
snapshot test caught the drift immediately. Regenerated via
`python -m tools.export_openapi_schema` (a 15-line, purely additive diff to
`docs/openapi/openapi.json`).

**A known, pre-existing blocker this ticket does not fix -- left exactly as
ticket 02 found and documented it, on the maintainer's own explicit
instruction.** The accepted `sqldbcontext` Contract on disk still declares
its methods' second parameter as `Microsoft.EntityFrameworkCore.SqlParameter[]?`,
a stale decompilation-cache artifact from before the current decompiler
existed (confirmed again this session: no `"EntityFrameworkCore"` string
exists anywhere under `tools/StaticAnalyzerHost/` today; the real type,
confirmed directly against `CommonLibrary.dll` with `ICSharpCode.Decompiler`,
is `Microsoft.Data.SqlClient.SqlParameter[]`). This means the strict
method-identity/parameter-type match in `_wrapper_contract_method_direct`
still rejects the real `usp_ExecCmdGetDataTableAsync` (and
`usp_ExecCmdGetDataSetAsync`, `usp_ExecCmdGetCountAsync`) call sites against
the real, on-disk Contract today, with or without this ticket's alias --
exactly the situation ticket 02's own Notes predicted and asked this
ticket's implementer to fix by re-decompiling and re-accepting `sqldbcontext`.

This session asked the maintainer directly whether to do that live fix now.
Fixing it means: re-decompiling `SQLDbContext` with `--force-rerun`,
re-accepting the result (which, because an accepted Contract is immutable,
lands under a *new* revision name, never overwriting `sqldbcontext` itself),
and then repointing IQCS's `wrapper_contract` selector in
`llamaindex-spec-rag/catalog/system_catalog.json` -- a file outside this git
repository entirely -- from the literal name `sqldbcontext` to that new
revision name, since the catalog selects by name, not by fingerprint. That
also changes what every other System sharing this Contract resolves against.
The maintainer chose to defer this and keep the current state. Both
mechanism-only acceptance bullets above (`usp_ExecCmdGetDataTableAsync`
resolving, and the review-line provenance) are proven instead against a
Contract fixture that declares the call sites' true parameter types --
the same technique `tests/test_rating_time_command_mode.py` used for ticket
02 -- run against the real IQCS source in
`tests/test_delegation_alias.py::test_the_real_usp_exec_cmd_get_data_table_async_call_resolves_through_its_alias`.
**Whoever next re-measures the coverage report, or picks up the remaining
`SQLFunc`/`SQLObject` re-decompile work implied by their own
`skipped_stale_cache_schema` result, should re-decompile and re-accept all
three -- and update the catalog selector -- together**, since all three
share this exact defect.

**Testing.** New files `tests/test_contract_migrations.py` (5 tests) and
`tests/test_delegation_alias.py` (6 tests: the real-checkout resolution, a
regression guard proving the same call fails without the alias, direct-match-
always-wins, an alias pointing at a missing operation reports the original
failure rather than a new one, case-insensitive alias lookup, and a Contract
with no `delegation_aliases` key behaving exactly as before). One test added
to the existing `tests/test_external_wrapper_contract_identity.py` for the
fresh-acceptance path. Full suite:
`python3 -m pytest tests/ --ignore=tests/test_search_roles.py --ignore=tests/test_sp_tables.py`
-- 979 passed, 11 failed; the failing set is byte-identical (same 11 test
names) to a `git stash` run against the unmodified base commit -- pre-
existing, unrelated to this ticket. C# host: `dotnet build`, 0 warnings, 0
errors (untouched this ticket -- the decompiler has recorded
`delegated_methods` since ticket 01/02; this ticket is entirely
Python-side consumption of that existing finding).
