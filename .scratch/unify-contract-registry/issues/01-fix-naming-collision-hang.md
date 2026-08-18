# 01 — Fix the contract-name collision hang

**What to build:** A system operator submitting a contract proposal through explicit acceptance never hangs, even when the proposal's fingerprint-derived name collides with every existing suffixed variant of an already-taken contract name. The naming-collision algorithm that makes this safe exists in exactly one place and is used by both the automatic refresh path and the explicit acceptance path.

**Blocked by:** None — can start immediately

**Status:** resolved

- [x] `service/contract_registry.py` exists with `find_casefold`, `taken_contract_name`, and `unused_revision_name` — the always-terminating algorithm (three fingerprint-length suffixes, then an incrementing ordinal fallback) already used by `contract_preflight.py`.
- [x] `contract_preflight.py` imports these three functions from the shared module and no longer defines its own private copies.
- [x] `contract_acceptance.py` imports `find_casefold` from the shared module and no longer defines its own private copy.
- [x] `contract_acceptance.py`'s `_prepare_versioned_registry` calls the shared `unused_revision_name` (passing an empty staged-names collection, since it only ever resolves one proposal at a time) instead of its own inline suffix-picking loop. The non-terminating oscillation between two already-taken names is gone.
- [x] Direct unit tests cover `find_casefold`, `taken_contract_name`, and `unused_revision_name`, including the three-way collision case (short, medium, and full-fingerprint suffixes all already taken) asserting the ordinal fallback is used and the call returns promptly.
- [x] A regression test through the existing `accept_external_wrapper_contract` entry point reproduces the same three-way collision and asserts it returns a valid, distinct contract name within a bounded time instead of hanging.
- [x] Existing `contract_preflight`/`contract_acceptance` test suites pass unmodified, except any test that directly exercised the now-removed private duplicate functions (those are updated to target the shared module instead).
