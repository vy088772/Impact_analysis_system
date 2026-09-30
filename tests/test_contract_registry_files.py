"""Smoke tests for the contract registry files.

`tests/conftest.py` pins the registry that the other tests read. These tests
read the live registry and the pinned fixtures with the production loader, so a
broken live file or a fixture that drifts from the production format fails here.
They do not pin the overload lists, because those change each time an operator
accepts a contract.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer import csharp_analysis_gateway
from service.contract_registry import DEFAULT_REGISTRY_PATH, load_contract_registry

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
REGISTRY_FIXTURES = sorted(FIXTURES.glob("*contracts*.json"))


@pytest.mark.live_registry
def test_the_live_registry_loads_under_strict_validation_and_normalizes():
    registry = load_contract_registry(DEFAULT_REGISTRY_PATH, strict=True)
    normalized = csharp_analysis_gateway._load_external_wrapper_contracts()

    assert {"sqlfunc", "sqlobject"} <= set(normalized)
    assert set(normalized) == set(registry["contracts"])


@pytest.mark.parametrize("fixture", REGISTRY_FIXTURES, ids=lambda path: path.name)
def test_each_pinned_fixture_passes_the_production_validation(fixture: Path):
    registry = load_contract_registry(fixture, strict=True)
    normalized = csharp_analysis_gateway._normalize_external_wrapper_contract_registry(registry)

    assert registry["contracts"]
    assert set(normalized) == set(registry["contracts"])
