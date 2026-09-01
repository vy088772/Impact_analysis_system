# 04 — A stored-procedure reverse lookup reuses rated Database Invocations

**What to build:** Asking twice which programs call a stored procedure rates the
repository's C# facts once, not twice. The second question is answered from the
evidence the first one derived, and the answer is identical either way.

This is the smaller half of the reuse, taken first on purpose. The stored-
procedure lookup needs only the rating step, so it exercises the retention and
the freshness rules without the path-building step on top. If the freshness
design is wrong, it is found here, on the lookup that is not carrying the bulk of
the measured wait.

Reuse arrives guarded, never on its own. Serving retained evidence after one of
its inputs has moved does not produce a slow answer, it produces a confidently
wrong one, and nothing in the response would reveal it. That is why the validity
stamp is part of this ticket rather than a follow-up, and why each invalidation
trigger is proven separately instead of collectively.

**Blocked by:** 02 (the baseline can never be taken once behaviour changes),
03 (there is no key without an explicit scope).

**Status:** done

- [x] Two consecutive stored-procedure lookups in one scope rate the repository's
      C# facts once
- [x] The answer is identical with reuse active and with reuse defeated — for a
      stored procedure with matches and for one with none
- [x] Each retained derivation carries a validity stamp covering the repository
      scan, the SQL cache it was joined against, the external wrapper contract,
      the contract registry, and the wrapper review exclusions
- [x] A mismatch on any single stamped input causes a fresh derivation, proven by
      one test per input, each also asserting the answer reflects the new input
- [x] An explicit refresh always derives again and replaces the retained entry,
      and is never served from retention
- [x] The lookup's response is unchanged in shape and content
- [x] Tests are driven through the lookup itself, the seam this area is already
      tested at, and assert derivation counts rather than elapsed time
- [x] Retained state is snapshotted and restored around tests, following the
      existing fixture that does this for the SQL cache's in-memory retention, so
      no test passes because of another test's leftovers

**Note:** `find_by_sp()`'s rating step (`_rated_execution_invocations`) is now
wrapped by `_rated_execution_invocations_for_scope()` in
`service/analyze_service.py`, which serves a retained result from the new
module-global `_rated_invocations_retention` dict (keyed by
`DerivedExecutionEvidenceScope`, unbounded per this ticket — ticket 06 states
and justifies the bound) whenever a freshly taken `_RatedInvocationsValidityStamp`
still matches the one stored alongside the retained entry, and always
re-derives and replaces the entry otherwise (stamp mismatch, or `req.refresh`).

The stamp covers all five inputs named in ADR-0013: the repository scan and
the SQL cache compare by Python object identity (both `scan_store` and
`sql_cache_store` hand back the same in-memory object across calls until a
refresh replaces it in their own — unbounded, never-evicted — process caches,
so identity already means "has this input moved"); the three rating-time
configuration reads (external wrapper contract, contract registry, wrapper
review exclusions) compare by value, since they are re-parsed from disk on
every call with no identity guarantee. A new helper,
`_rating_config_inputs(scope)`, makes exactly one such read per input and now
backs both the stamp and `_rated_execution_invocations` itself, so the
freshness check and the rating step can never drift apart by reading these
through two different paths.

One correctness subtlety worth recording: the scan identity is taken from
`per_root_scans` — the caller's list of per-root scan objects *before* any
multi-root merge — not from the (possibly merged) `scan` object the rating
step actually joins against. `_merge_scans()` always builds a brand-new
`ProjectScanResult` on every call, even when nothing changed, so it can never
itself serve as the "has the scan moved" signal; `_get_scan()` per root does
hand back a stable object until refreshed, so that is what the stamp reads.

Added `tests/test_derived_execution_evidence_reuse.py` (11 tests) and
`tests/derived_execution_evidence_fixtures.py` (a `RatedInvocationsRetention`
snapshot/restore context manager, mirroring `tests/sql_cache_fixtures.py`'s
`CacheRoot`), driven entirely through `find_by_sp()`: two consecutive lookups
and two different-SP-name lookups in one scope each rate the facts once
(proving question-independence, not just repetition-independence); the answer
is identical with reuse active vs. reuse manually defeated, for a match and
for no match; one invalidation test per stamped input (repository scan, SQL
cache, external wrapper contract, contract registry, wrapper review
exclusions), each asserting both a second derivation and a changed response —
the three configuration-input tests install a small rating stand-in whose one
PROVEN match's procedure name is read live from the (possibly monkeypatched)
loader at call time, so the response visibly changes without needing to
reconstruct `CSharpAnalysisGateway`'s own wrapper-contract resolution rules,
which are that module's concern, not this retention layer's; an explicit
refresh always re-derives (asserted across three calls, two of them
`refresh=True`); and a dedicated fixture test proves snapshot/restore actually
isolates a pre-existing entry and a during-test entry from each other.

Ran the full suite before and after (`git stash` / restore) and diffed the
failing-test lists excluding the two ODBC-driver collection failures already
known from ticket 03: identical in both cases (the same 12 pre-existing
failures, none of them touching this change). Confirmed one of the tests
(`test_a_changed_contract_registry_causes_a_fresh_derivation`) actually
detects a regression by temporarily breaking the stamp to drop the contract
registry field, watching that test fail, then restoring the real
implementation. No mypy config exists in this repository;
`python -m py_compile` confirms all changed/new files are syntactically sound.

Two review sub-agents ran the Standards and Spec axes in parallel against the
diff. Standards flagged the retention dict's original
`_RATED_INVOCATIONS_RETENTION` name as inconsistent with this file's existing
lowercase process-global cache (`_scan_cache`), and flagged that
`_rated_execution_invocations` still read the three rating configs inline
instead of through the newly extracted `_rating_config_inputs()` — both fixed.
Spec flagged that three of the five invalidation tests (external wrapper
contract, contract registry, wrapper review exclusions) only asserted a
derivation-count change, not a response-content change, missing the
checklist's "each also asserting the answer reflects the new input" — fixed
by rewriting those three tests as described above. No scope creep was found
in either review: `find_by_table()`, `flow_chain()`, `analyze()`, and
`get_path_evidence()` are untouched, and no retention bound was added ahead of
ticket 06.
