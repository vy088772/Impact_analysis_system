# 02 — Add the shared registry loader

**What to build:** One function in `service/contract_registry.py` owns "how do I safely read the external wrapper contract registry," reproducing both of today's existing behaviors exactly under one explicit flag. The automatic refresh path (`analyze_service.py`) is migrated onto it with zero behavior change. The registry/catalog path constants exist in exactly one place.

**Blocked by:** 01 — builds on the same new module

**Status:** resolved

- [x] `load_contract_registry(path, *, strict=False)` is added to `service/contract_registry.py`.
- [x] `strict=False` reproduces `contract_preflight.py`'s current behavior exactly: a missing or unparseable registry file degrades to `{"contracts": {}}`; registry content is never validated, and whatever parses is returned as-is.
- [x] `strict=True` reproduces `contract_acceptance.py`'s current behavior exactly: a missing or unparseable file raises; registry content is validated (non-empty contract names, no casefold-duplicate names, every contract entry object-shaped), raising on any violation.
- [x] A new `ContractRegistryError` exception type is defined in the shared module (carrying `code`, `message`, `details`) and raised only by strict-mode failures. It has no dependency on `contract_acceptance.ContractAcceptanceError`.
- [x] `DEFAULT_REGISTRY_PATH` and `DEFAULT_CATALOG_PATH` are declared once, in the shared module. `contract_transaction.py` imports them from there instead of declaring its own copies.
- [x] `analyze_service.py` imports `load_contract_registry` from the shared module instead of from `contract_preflight.py`. Call sites and call signature (default `strict=False`) are unchanged.
- [x] `contract_preflight.py`'s own `load_contract_registry` is removed, since nothing calls it anymore. `_registry_entries`/`_registry_payload` also moved into the shared module (the non-strict loader needs the same coercion logic internally) and are imported back into `contract_preflight.py` by name — they could not be deleted outright, since `normalize_contract_selector`, `_stage_complete_proposals`, `run_contract_preflight`, and `ContractPreflightResult.to_dict` still use them to normalize already-in-memory registry mappings, a concern unrelated to file loading.
- [x] Direct unit tests cover both `strict=False` and `strict=True` behavior of `load_contract_registry`, including missing-file, unparseable-JSON, and malformed-content cases for each mode.
- [x] Existing tests that monkeypatch `load_contract_registry` on the `analyze_service` module attribute (`tests/test_refresh_atomic_commit.py`, `tests/test_refresh_decompile_onboarding.py`) pass unmodified.
- [x] `contract_acceptance.py` is not touched in this ticket — it still defines and uses its own loader; migrating it is ticket 03.
