"""Test fixtures shared by the whole suite.

The live registry `config/external_wrapper_contracts.json` holds the contracts
that the refresh tool decompiled from real assemblies. Its overload lists change
each time an operator accepts a contract. A test that reads it breaks when the
registry changes. This file pins the registry that the gateway, the analysis
service, and the Derived Execution Evidence module read by default to
`fixtures/external_wrapper_contracts.json`: one entry for each `sqlobject`
method with no signature, the fixed `sqldbcontext` entry of ticket 01, and the
decompiled `sqlfunc` contract. A test that needs a signature for each method
(`external_wrapper_contracts_signed.json`) or that passes a registry or a path of
its own is not affected.
"""

import json
from pathlib import Path

import pytest

from code_analyzer import csharp_analysis_gateway
from service import analyze_service, contract_registry, derived_execution_evidence

PINNED_REGISTRY = Path(__file__).parent / "fixtures" / "external_wrapper_contracts.json"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live_registry: read the live contract registry, with no pin"
    )


@pytest.fixture(autouse=True)
def _pinned_contract_registry(request, monkeypatch):
    if request.node.get_closest_marker("live_registry"):
        return
    payload = json.loads(PINNED_REGISTRY.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        csharp_analysis_gateway,
        "_load_external_wrapper_contracts",
        lambda: csharp_analysis_gateway._normalize_external_wrapper_contract_registry(payload),
    )
    load_registry = contract_registry.load_contract_registry
    for module in (analyze_service, derived_execution_evidence):
        monkeypatch.setattr(
            module,
            "load_contract_registry",
            lambda path=PINNED_REGISTRY, **kwargs: load_registry(path, **kwargs),
        )
