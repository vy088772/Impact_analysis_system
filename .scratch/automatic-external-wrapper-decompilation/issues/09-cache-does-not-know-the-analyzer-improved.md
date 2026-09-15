# 09 — The decompilation cache does not know when the analyzer itself improves, and its already-computed summary is invisible in `refresh_cli`

**What to build:** Two related visibility gaps, found together while
investigating why a full IQCS refresh still reports
`onboarding=preflight_failed` for `SQLDbContext` after tickets 01-08 of
`wrapper-command-source-efcore-async` landed and were verified resolved.

**Cause 1 — the cache is keyed only on the DLL's hash, never on the analyzer's own logic.**
Ticket 04 of this spec deliberately keyed `DecompilationAttemptCache` on the
DLL's SHA-256 hash alone, invalidated only by a hash change or an explicit
re-run (see that ticket's "What to build"). That was correct for its own
scope, but it did not anticipate this case: `CommonLibrary.dll` never changed,
but the analyzer's own classification of it did, three separate times, across
`wrapper-command-source-efcore-async` tickets 01, 02/07, and 04. Every one of
those improvements left the *old*, `database_behavior_surface_incomplete`
attempt sitting in `data/decompilation_cache/<hash>.json` from before any of
them landed, because nothing about a code change to the analyzer bumps a DLL's
hash. A fresh decompilation, run directly against the same DLL bypassing this
cache, succeeds completely today — `public_database_operations_complete: true`,
zero unclassified methods, a valid Contract fingerprint. The cached one still
reports all seven methods unclassified. `run_contract_preflight` reads the
cache, not the DLL, so it still reports `preflight_failed` for a Contract that
current code can already build correctly.

**Cause 2 — the decompilation attempt summary already reaches the HTTP response, but `refresh_cli` never prints it.**
`_decompilation_summary()` and `_populate_decompilation_proposals()`
(`service/analyze_service.py`) already compute exactly what
`automatic-external-wrapper-decompilation`'s own ticket 05 asked for — per
receiver-type attempt outcome and incomplete reasons — and `refresh_source`
already assigns it to `wrapper_summary["decompilation"]`. `WrapperSummary`'s
`extra="allow"` config already lets it survive to the JSON response
un-dropped. But `llamaindex-spec-rag/impact_orch/refresh_cli.py` has no
printer for it at all — `_print_wrapper_summary` and
`_print_contract_transaction` exist; nothing reads `wrapper_summary["decompilation"]`.
An operator debugging exactly this class of issue has to reproduce it by hand
in a Python shell, as this investigation did, instead of reading it off the
refresh output.

**Blocked by:** None — can start immediately. Independent of
`wrapper-receiver-resolves-through-interface` (a separate spec from the same
investigation).

**Status:** done

- [x] `DecompilationAttemptCache` additionally stores a `host_identity` value
      (a SHA-256 of the compiled `StaticAnalyzerHost` binary, computed the same
      way `assembly_identity` already is) alongside the existing
      `cache_version` and DLL `assembly_identity` keys
- [x] A cached document whose `host_identity` does not match the current host
      binary's hash is treated as a miss — the same treatment `cache_version`
      mismatch already receives in `_load_document` — not as a cached failure
- [x] `host_identity` is computed once per `StaticAnalyzerHost` instance (not
      once per receiver-type lookup), since a refresh may call
      `decompile_wrapper` for dozens of receiver types in one run
- [x] A cache document written before this change (no `host_identity` field at
      all) is treated as a miss, so every existing cache entry — including
      `SQLDbContext`'s — is automatically re-attempted on the next refresh,
      with no manual `rerun_receiver_types` step required
- [x] `refresh_cli.py` gains a `_print_decompilation_summary(data)` printer,
      called from `main()` alongside the existing wrapper-summary and
      contract-transaction printers, reading `wrapper_summary["decompilation"]`
      and printing outcome and reasons per attempted receiver type
- [x] A refresh that attempts no decompilation (valid selector already
      configured, or a program-scoped refresh) prints no decompilation line,
      matching the existing suppression pattern used for the wrapper-summary
      and contract-transaction printers
- [x] Re-running `python -m impact_orch.refresh_cli IQCS` after this ticket
      lands reports a committed `sqldbcontext` Contract with no manual step,
      and the decompilation line names `SQLDbContext` as `complete`

## Comments

Implemented in two repos: `Impact_analysis_system` (Cause 1 — the cache
itself) and `llamaindex-spec-rag` (Cause 2 — `refresh_cli.py`'s printer).

**Deviation from the literal checklist wording:** `host_identity` ended up
stored per receiver-type attempt entry (`attempts[receiver_type].host_identity`),
not once at the whole document's top level as the first four bullets read
literally. A document-level field was tried first and built exactly as
written, but it has a real bug on the shape this ticket's own repro uses:
`CommonLibrary.dll` caches dozens of receiver types in one file. Bumping one
shared `host_identity` field on save either wipes every sibling receiver
type's cached attempt, or — worse — lets an untouched, still-stale sibling
start being served as a cache hit purely because a different receiver type in
the same file was re-verified. That is exactly the silent-staleness failure
[ADR-0026](../../../docs/adr/0026-decompilation-cache-keys-on-the-analyzer-hosts-own-identity.md)
exists to rule out, so the field moved to per-attempt granularity instead.
Every observable behavior the checklist asks for (miss on missing/mismatched
identity, no manual `rerun_receiver_types` step, `SQLDbContext` reclassifying)
still holds under this design — see
`test_client_cache_re_saving_one_stale_receiver_type_does_not_revive_a_sibling`
in `tests/test_wrapper_decompilation.py`, which reproduces and pins down the
sibling-corruption failure mode the document-level version had.

**Real end-to-end verification:** last bullet was verified directly against
`code_analyzer/static_analyzer_host.py`'s `decompile_wrapper()` using the
actual on-disk `data/repos/System_Dept_1/IQCS/IQCS.csproj` +
`CommonLibrary.dll` (rather than through a live `refresh_cli.py` run against a
running Impact service and a real SQL Server connection, which this
environment cannot reach — no ODBC driver installed). The pre-existing stale
cache entry for `SQLDbContext` (`attempt_outcome: incomplete`) was
automatically treated as a miss and re-decompiled to
`attempt_outcome: complete`, with one contract proposal, with no manual
`rerun` step.

Two-axis code review (Standards + Spec, both parallel sub-agents) ran clean:
no hard standards violations, no missing/wrong spec requirements, no scope
creep beyond fixing a stale test comment. Minor duplicated-rationale-text and
docstring-precision nits were judgment calls, one of which (the
`_print_decompilation_summary` suppression check) was tightened to an
explicit early-return to match its sibling printers exactly.

Side effect during testing: the shared local `data/decompilation_cache/`
files (gitignored, not shipped) lost their non-`SQLDbContext` entries for
`CommonLibrary.dll` while the document-level design was still in place. This
is inconsequential — that data regenerates on the next refresh, which is the
accepted one-time cost ADR-0026 already documents for any host rebuild.

**Note:** this is a change to a decision `automatic-external-wrapper-decompilation`
already made deliberately (cache keyed on DLL hash only) — see
[ADR-0026](../../../docs/adr/0026-decompilation-cache-keys-on-the-analyzer-hosts-own-identity.md)
for why the boundary is widened rather than reversed, and its accepted
consequence: rebuilding the analyzer host invalidates every system's
decompilation cache at once, trading a slower first refresh after a host
rebuild for never silently trusting a stale classification again.
