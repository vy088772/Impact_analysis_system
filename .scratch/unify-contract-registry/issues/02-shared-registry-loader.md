# 02 — Add the shared registry loader

**What to build:** One function in `service/contract_registry.py` owns "how do I safely read the external wrapper contract registry," reproducing both of today's existing behaviors exactly under one explicit flag. The automatic refresh path (`analyze_service.py`) is migrated onto it with zero behavior change. The registry/catalog path constants exist in exactly one place.

**Blocked by:** 01 — builds on the same new module

**Status:** ready-for-agent

- [ ] `load_contract_registry(path, *, strict=False)` is added to `service/contract_registry.py`.
- [ ] `strict=False` reproduces `contract_preflight.py`'s current behavior exactly: a missing or unparseable registry file degrades to `{"contracts": {}}`; registry content is never validated, and whatever parses is returned as-is.
- [ ] `strict=True` reproduces `contract_acceptance.py`'s current behavior exactly: a missing or unparseable file raises; registry content is validated (non-empty contract names, no casefold-duplicate names, every contract entry object-shaped), raising on any violation.
- [ ] A new `ContractRegistryError` exception type is defined in the shared module (carrying `code`, `message`, `details`) and raised only by strict-mode failures. It has no dependency on `contract_acceptance.ContractAcceptanceError`.
- [ ] `DEFAULT_REGISTRY_PATH` and `DEFAULT_CATALOG_PATH` are declared once, in the shared module. `contract_transaction.py` imports them from there instead of declaring its own copies.
- [ ] `analyze_service.py` imports `load_contract_registry` from the shared module instead of from `contract_preflight.py`. Call sites and call signature (default `strict=False`) are unchanged.
- [ ] `contract_preflight.py`'s own `load_contract_registry`, `_registry_entries`, and `_registry_payload` are removed, since nothing calls them anymore.
- [ ] Direct unit tests cover both `strict=False` and `strict=True` behavior of `load_contract_registry`, including missing-file, unparseable-JSON, and malformed-content cases for each mode.
- [ ] Existing tests that monkeypatch `load_contract_registry` on the `analyze_service` module attribute (`tests/test_refresh_atomic_commit.py`, `tests/test_refresh_decompile_onboarding.py`) pass unmodified.
- [ ] `contract_acceptance.py` is not touched in this ticket — it still defines and uses its own loader; migrating it is ticket 03.
