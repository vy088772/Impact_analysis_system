# 03 — Migrate contract acceptance onto the shared strict loader

**What to build:** The explicit contract-acceptance workflow reads the registry through the same shared module as the automatic refresh path, with its existing strict behavior and its existing external error contract both preserved exactly. `contract_acceptance.py` no longer maintains its own copy of registry-loading or content-validation logic.

**Blocked by:** 02 — needs the shared strict-mode loader to exist and be tested

**Status:** resolved

- [x] `contract_acceptance.py` calls the shared `load_contract_registry(path, strict=True)` in place of its own loading function.
- [x] Any `ContractRegistryError` raised at that call site is translated into `ContractAcceptanceError(exc.code, str(exc), exc.details)` — same code and details, existing exception type.
- [x] `contract_acceptance.py`'s own `load_contract_registry` and `_contract_entries` are removed.
- [x] `_prepare_registry` and `_prepare_versioned_registry`'s internal re-validation calls (which validate the already-loaded registry a second time) call the shared module's validation logic instead of the local copy. The double-validation itself is unchanged — only the implementation it calls is shared now.
- [x] `service/api.py`'s `/wrapper_contracts/accept` endpoint and `tools/accept_external_wrapper_contract.py` require no changes — their existing handling of `ContractAcceptanceError.code`/`.details` keeps working.
- [x] The existing `tests/test_contract_acceptance.py` suite passes unmodified, including tests asserting error codes for missing, invalid, and structurally malformed registry files.
