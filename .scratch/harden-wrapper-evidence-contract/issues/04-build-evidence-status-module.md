# 04 — Build the evidence_status module

**What to build:** In `llamaindex-spec-rag`'s `impact_orch` package, one new module owns interpreting this service's Evidence Status data. It exposes exactly three functions: an accessor parsing a Database Invocation's own evidence rating into a typed value, a separately-named accessor parsing a wrapper-evidence-bag's evidence status into its own typed value (including the `not_applicable` sentinel), and a boolean helper reporting whether a given typed value counts as verified (`proven`/`likely`) versus unresolved. The two accessors return genuinely separate types so a caller cannot accidentally pass one concept's raw data to the other's accessor. This ticket only builds and unit-tests the module — it is not wired into any existing call site yet.

**Blocked by:** 01 — the module is built against this service's now-typed `/refresh` contract, not guessed ahead of it.

**Status:** done

- [x] One accessor parses a Database Invocation's own evidence rating from raw response data into a typed value
- [x] A separately-named, separately-typed accessor parses a wrapper-evidence-bag's evidence status from raw response data, including `not_applicable`
- [x] A boolean helper takes either typed value and reports verified vs. unresolved
- [x] Unit tests cover all four known values for each accessor
- [x] A unit test confirms an unrecognized/future value fails loudly rather than silently defaulting
- [x] No existing call site (`context_builder.py`, `path_selection.py`, `refresh_cli.py`, `rag_client.py`) is modified by this ticket

`llamaindex-spec-rag/impact_orch/evidence_status.py` created, with `tests/test_evidence_status.py` (23 tests, all passing). Two separate `Enum` types — `DbInvocationEvidenceRating` (parses a flat `evidence` key) and `WrapperEvidenceBagStatus` (parses an `evidence_status` key) — both closed over this service's four-value controlled vocabulary (`proven`/`likely`/`unresolved`/`not_applicable`), plus `is_verified()`. An unrecognized value raises `UnknownEvidenceStatusError` (a `ValueError` subclass) instead of defaulting. No call site was touched — that's ticket 06/07.
