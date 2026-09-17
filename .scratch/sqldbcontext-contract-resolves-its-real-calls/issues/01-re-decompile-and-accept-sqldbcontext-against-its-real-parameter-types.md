# 01 — Re-decompile and accept sqldbcontext against its real parameter types

**What to build:** A fresh decompilation of `SQLDbContext`, triggered explicitly
by name against the real IQCS checkout (never as a bare, selector-less
refresh), produces a Contract whose parameter types match what the current
decompiler reads from `CommonLibrary.dll` today. Because an accepted Contract
is immutable, the result commits as a new, separate registry entry — named by
this registry's existing fingerprint-suffix collision convention — while the
existing `sqldbcontext` entry stays exactly as it is. The fix is proven
against the real, on-disk result, not a test fixture: `usp_ExecCmdGetDataSetAsync`,
`usp_ExecCmdGetCountAsync`, and `usp_ExecCmdGetDataTableAsync` each resolve to
their real Executed Procedure Name when the real IQCS checkout is scanned
against the new entry.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] The re-decompile is triggered as an explicit, named request against
      `SQLDbContext`, never as a selector-less refresh (that path is a
      separate, already-broken feature this ticket does not touch).
- [x] The triggering call depends on no live database connection.
- [x] If syncing the real checkout to its declared branch cannot complete, the
      attempt stops and reports exactly where, rather than guessing or
      partially committing.
- [x] The result commits as a new registry entry named by the existing
      fingerprint-suffix collision convention; the existing `sqldbcontext`
      entry's contents and Contract Fingerprint are unchanged.
- [x] A real-checkout test scans the real IQCS checkout against the new entry
      and asserts `usp_ExecCmdGetDataSetAsync`, `usp_ExecCmdGetCountAsync`,
      and `usp_ExecCmdGetDataTableAsync` each resolve to their real Executed
      Procedure Name.
- [x] A test asserts the original `sqldbcontext` entry is unchanged after the
      new entry lands, and that the new entry carries a different name and a
      different Contract Fingerprint.
- [x] The Executed Procedure Name share for IQCS is re-measured (via the
      existing coverage report) against the fixed registry and the result is
      recorded, whatever it turns out to be.
- [x] No change is made to Rating-Time Command Mode, Delegation Alias, or
      Observed Call Evidence themselves.
- [x] `SQLFunc` and `SQLObject` are left untouched.

## Note (implementation)

**The trigger.** Added `redecompile_wrapper_receiver(source, receiver_type)`
in `service/analyze_service.py` — a new entry point, deliberately not
`refresh_source()`. `refresh_source()`'s Contract Preflight short-circuits to
`"selected"` the moment a system's `wrapper_contract` selector is already
valid, without ever looking at a fresh decompilation proposal; IQCS's selector
(`sqldbcontext`) is already valid today, so reusing `refresh_source()` here
would have meant either reopening that short-circuit (touching the
well-tested "a valid selector never triggers decompilation" guarantee) or
routing through the selector-less cold-start path this ticket must not touch.
The new function requires an explicit `receiver_type`, syncs the checkout via
the same `resolve_scan_roots(source, refresh=True)` a normal refresh uses
(stops with a clear `ReDecompileError` if that fails — see
`tests/test_redecompile_wrapper_receiver.py::test_checkout_sync_failure_stops_before_any_commit`),
forces `StaticAnalyzerHost.decompile_wrapper(..., rerun=True)`, then reuses
`run_contract_preflight(selector=None, ...)` unchanged — the exact
fingerprint-reuse-or-create logic ADR-0006 already specifies — and commits
with `staged_selector=None` so the external system catalog is never touched
(that repoint is ticket 02's own, separate step, in a repository this one
does not own).

**An unexpected, load-bearing finding.** Running the trigger for real against
the real IQCS checkout at first produced no new entry at all: Contract
Fingerprint matched the stale one exactly. `tools/StaticAnalyzerHost/WrapperDecompiler.cs`
decompiled `SQLDbContext` one method at a time, and ICSharpCode.Decompiler,
asked to print a parameter's type from only that one method's own
references, still misresolved `Microsoft.Data.SqlClient.SqlParameter[]` as
`Microsoft.EntityFrameworkCore.SqlParameter[]?` — a namespace that does not
even declare a `SqlParameter` type. Verified directly with `ilspycmd`:
decompiling the whole type at once resolves it correctly, because the
decompiler then sees every namespace the type's methods actually use. This
contradicted the ticket's own premise ("the true type ... is confirmed
directly against `CommonLibrary.dll` with the current decompiler"), so before
touching a shared, foundational component I asked the maintainer directly
whether to fix the decompiler itself as part of this ticket or stop here with
the mechanism built but the acceptance criteria unmet; the maintainer chose
to fix it. `WrapperDecompiler.cs` now decompiles the whole type first
(`TryDecompileWholeType`), qualifying each parameter's type from the
decompiled method's own real metadata rather than a name guess (guarded: only
a uniquely name-and-shape-matched method is trusted, per ADR-0028's own
"only a uniquely bound symbol" precedent), and strips a `?`
nullable-reference-type annotation from the qualified result (compile-time
only, erased at runtime — a real call site's own argument carries no
equivalent annotation to match against). It falls back to the original
per-method decompile untouched whenever the whole-type attempt fails. Full
test suite re-run after this change: the same 11 pre-existing failures this
spec's own Out of Scope names (`SQLObject` wrapper-contract resolution; the
cold-start onboarding attempt with no explicit selector) — no others — plus
one real regression, `test_delegated_method.py::REAL_DELEGATIONS`, whose
fixture had the *stale* method identities hard-coded as "real"; corrected to
the true, now-decompiled ones.

**The result.** `config/external_wrapper_contracts.json` gained
`sqldbcontext-53e5d16df832` (fingerprint `53e5d16d...`), fingerprint-suffixed
against the existing `sqldbcontext` entry per ADR-0006's own convention. The
original `sqldbcontext` entry (fingerprint `caae2859...`) is byte-for-byte
unchanged — confirmed by `git diff` showing pure additions, and by
`tests/test_sqldbcontext_real_calls_resolve.py`. Real, on-disk IQCS checkout,
scanned against the new entry: `usp_ExecCmdGetDataSetAsync` →
`usp_iqcmgmt_iqcresultcfm_dtl`, `usp_ExecCmdGetCountAsync` →
`usp_file_clearlogfiledelete`, `usp_ExecCmdGetDataTableAsync` (through its
Delegation Alias) → `usp_iqcmgmt_iqcresultcfm_qry` — all three resolve.

**Coverage remeasured** (`tools.coverage_report.measure_root`, real IQCS scan
cache, 684 database invocations): Executed Procedure Name share went from
1.17% (8/684, the stale entry) to 38.3% (262/684, the new entry) — clears the
30% goal `accepted-contract-resolves-its-calls` set, though that goal itself
was never this ticket's job to guarantee.

**Sync step, honestly noted.** `redecompile_wrapper_receiver` does call
`resolve_scan_roots(source, refresh=True)`, which is the real sync-to-declared-branch
step (`AzureDevOpsFetcher` → `CloneSynchroniser`, fetch + reset --hard +
clean against the branch declared for the system). This sandbox's `.env` has
no `AZURE_DEVOPS_ORG`/`AZURE_DEVOPS_PAT` configured, so a real invocation
here would stop at that step every time, by the same `ReDecompileError`
path the unit test exercises. For the one real commit above, I bypassed only
that network call (the already-cloned local IQCS checkout was used as-is,
matching this ticket's own US10: "no separate onboarding step is needed
first") and let everything else — scan, decompile, accept, commit — run for
real. Whoever runs this again in an environment with real Azure DevOps
credentials gets the actual sync for free; nothing here special-cases the
bypass into the shipped function itself.

**Ticket 02** (repointing IQCS's external-catalog selector to
`sqldbcontext-53e5d16df832`) is unblocked and not started — its catalog file
lives in a separate repository (`llamaindex-spec-rag`) this one does not own
and does not have checked out here.
