"""Explicit, named re-decompilation of one wrapper receiver type.

`redecompile_wrapper_receiver()` is the maintainer bypass ADR-0005/0006
already describe (`StaticAnalyzerHost.decompile_wrapper(..., rerun=True)`),
reached through an entry point that keeps working even when the system's own
`wrapper_contract` selector already resolves to an existing, accepted
Contract -- unlike `refresh_source()`, whose Contract Preflight short-circuits
to "selected" and never looks at a fresh decompilation proposal once a
selector is valid (see `test_valid_selector_never_triggers_decompilation` in
test_refresh_decompile_onboarding.py, which this module must not disturb).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.azure_fetcher import AzureFetchError
from code_analyzer.project_scanner import ProjectScanResult
from code_analyzer.static_analyzer_host import StaticAnalyzerHostError
from service import analyze_service


def _scan(root: Path, *, receiver_type: str = "SQLDbContext") -> ProjectScanResult:
    source_file = root / "QryService.cs"
    return ProjectScanResult(
        project_root=str(root),
        project_name=root.name,
        scan_time=datetime.now(),
        db_invocations={
            str(source_file): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "QryService",
                    "method_name": "Query",
                    "wrapper_method_name": "usp_ExecCmdGetDataSetAsync",
                    "wrapper_receiver_type": receiver_type,
                    "wrapper_source_available": False,
                    "wrapper_method_arity": 3,
                    "wrapper_parameter_types": ["string", "Microsoft.Data.SqlClient.SqlParameter[]", "bool"],
                    "wrapper_mode": "call_site",
                    "command_text_kind": "literal",
                    "command_text": "usp_ExecCmdGetDataSetAsync",
                    "connection_expression": "_db",
                    "start_offset": 1,
                    "end_offset": 20,
                }
            ]
        },
    )


def _write_referencing_project(root: Path, dll_name: str = "CommonLibrary.dll") -> Path:
    (root / "bin").mkdir(parents=True, exist_ok=True)
    (root / "bin" / dll_name).write_bytes(b"fixture")
    csproj = root / "IQCS.csproj"
    csproj.write_text(
        "<Project xmlns=\"http://schemas.microsoft.com/developer/msbuild/2003\">"
        "<ItemGroup>"
        f"<Reference Include=\"CommonLibrary, Version=1.0.0.0\">"
        f"<HintPath>bin\\{dll_name}</HintPath>"
        "</Reference>"
        "</ItemGroup>"
        "</Project>",
        encoding="utf-8",
    )
    return csproj


def _proposal(*, fingerprint_seed: str = "fresh") -> dict:
    return {
        "name": "SQLDbContext",
        "receiver_types": ["SQLDbContext"],
        "implementation_snapshot": {
            "artifact_identity": f"CommonLibrary.dll@sha256:{fingerprint_seed}",
            "assembly_identity": fingerprint_seed,
            "assembly_revision": fingerprint_seed,
            "behavior_surface_unit": "SQLDbContext",
            "complete": True,
            "methods": [
                {
                    "method_identity": "SQLDbContext.usp_ExecCmdGetDataSetAsync(string,Microsoft.Data.SqlClient.SqlParameter[],bool)",
                    "method_name": "usp_ExecCmdGetDataSetAsync",
                    "method_arity": 3,
                    "parameter_types": [
                        "string",
                        "Microsoft.Data.SqlClient.SqlParameter[]",
                        "bool",
                    ],
                    "required_parameter_count": 1,
                    "argument_roles": {"command_text": 0, "command_type": 2},
                    "effective_command_semantics": "call_site",
                    "terminal_sink": "ExecuteReaderAsync",
                    "connection_behavior_boundary": "context_connection",
                    "branch_rules": [{"mode": "call_site", "sink": "ExecuteReaderAsync"}],
                    "assembly_revision": fingerprint_seed,
                    "body_complete": True,
                }
            ],
            "helper_operations_complete": True,
            "inherited_operations_complete": True,
        },
    }


def _response(*, proposal: bool = True, outcome: str = "complete", fingerprint_seed: str = "fresh") -> dict:
    return {
        "status": "resolved" if outcome == "complete" else "decompile_failed",
        "attempt_outcome": outcome,
        "cache_status": "miss",
        "detail": "invalid IL" if outcome == "incomplete" else None,
        "decompilation_attempt": {
            "attempted": True,
            "outcome": outcome,
            "cache_status": "miss",
        },
        "contract_proposals": [_proposal(fingerprint_seed=fingerprint_seed)] if proposal else [],
        "translation_problem_methods": ["Broken"] if outcome == "incomplete" else [],
        "wrapper_definitions": [] if outcome == "incomplete" else [{"unresolved_reason": None}],
    }


def _patch_sync(monkeypatch, root: Path, scan: ProjectScanResult) -> None:
    monkeypatch.setattr(
        analyze_service,
        "resolve_scan_roots",
        lambda source, refresh=False: [root],
    )
    monkeypatch.setattr(
        analyze_service,
        "get_or_scan",
        lambda scan_root, refresh=False: scan,
    )
    monkeypatch.setattr(analyze_service, "cached_commit", lambda scan_root: "deadbeef")


def _patch_host(monkeypatch, responses: list[dict], calls: list[tuple[Path, str, bool]]) -> None:
    class FakeHost:
        @classmethod
        def for_project(cls, project_root: Path) -> "FakeHost":
            return cls()

        def ensure_ready(self) -> dict:
            return {"contract_version": 2}

        def decompile_wrapper(
            self, csproj_path: Path, receiver_type: str, *, rerun: bool = False
        ) -> dict:
            calls.append((Path(csproj_path), receiver_type, rerun))
            return responses[len(calls) - 1]

    monkeypatch.setattr(analyze_service, "StaticAnalyzerHost", FakeHost, raising=False)


_EXISTING_SQLDBCONTEXT_ENTRY = {
    "receiver_types": ["SQLDbContext"],
    "contract_fingerprint": "0" * 64,
    "behavior_signature": {"signature_version": "v1", "operations": []},
}


def test_empty_receiver_type_is_rejected(monkeypatch, tmp_path) -> None:
    calls: list = []
    monkeypatch.setattr(
        analyze_service,
        "resolve_scan_roots",
        lambda source, refresh=False: calls.append("called") or [tmp_path],
    )

    with pytest.raises(analyze_service.ReDecompileError) as exc_info:
        analyze_service.redecompile_wrapper_receiver({"project": "p", "repo": "r"}, "")

    assert exc_info.value.code == "receiver_type_required"
    assert calls == []


def test_checkout_sync_failure_stops_before_any_commit(monkeypatch, tmp_path) -> None:
    def _raise(source, refresh=False):
        raise AzureFetchError("找不到 dev.azure.com 主機")

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", _raise)
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(json.dumps({"contracts": {"sqldbcontext": _EXISTING_SQLDBCONTEXT_ENTRY}}))
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_REGISTRY_PATH", registry_path)

    with pytest.raises(analyze_service.ReDecompileError) as exc_info:
        analyze_service.redecompile_wrapper_receiver(
            {"project": "p", "repo": "r"}, "SQLDbContext"
        )

    assert exc_info.value.code == "checkout_sync_failed"
    assert json.loads(registry_path.read_text(encoding="utf-8")) == {
        "contracts": {"sqldbcontext": _EXISTING_SQLDBCONTEXT_ENTRY}
    }


def test_receiver_not_referenced_raises(monkeypatch, tmp_path) -> None:
    root = tmp_path / "IQCS"
    root.mkdir()
    scan = _scan(root, receiver_type="SomeOtherReceiver")
    _patch_sync(monkeypatch, root, scan)

    with pytest.raises(analyze_service.ReDecompileError) as exc_info:
        analyze_service.redecompile_wrapper_receiver(
            {"project": "p", "repo": "r"}, "SQLDbContext"
        )

    assert exc_info.value.code == "receiver_not_referenced"


def test_csproj_not_found_raises(monkeypatch, tmp_path) -> None:
    root = tmp_path / "IQCS"
    root.mkdir()
    scan = _scan(root)
    _patch_sync(monkeypatch, root, scan)

    with pytest.raises(analyze_service.ReDecompileError) as exc_info:
        analyze_service.redecompile_wrapper_receiver(
            {"project": "p", "repo": "r"}, "SQLDbContext"
        )

    assert exc_info.value.code == "csproj_not_found"


def test_incomplete_decompilation_raises(monkeypatch, tmp_path) -> None:
    root = tmp_path / "IQCS"
    root.mkdir()
    csproj = _write_referencing_project(root)
    scan = _scan(root)
    calls: list = []
    _patch_sync(monkeypatch, root, scan)
    _patch_host(monkeypatch, [_response(proposal=False, outcome="incomplete")], calls)

    with pytest.raises(analyze_service.ReDecompileError) as exc_info:
        analyze_service.redecompile_wrapper_receiver(
            {"project": "p", "repo": "r"}, "SQLDbContext"
        )

    assert exc_info.value.code == "decompilation_incomplete"
    assert calls == [(csproj, "SQLDbContext", True)]


def test_always_forces_rerun_past_any_cached_attempt(monkeypatch, tmp_path) -> None:
    """The whole point of this entry point is to bypass a cached attempt for
    this one receiver type (US of ticket 01) -- `rerun` must always be True,
    never left to whatever the host's own cache last held."""
    root = tmp_path / "IQCS"
    root.mkdir()
    _write_referencing_project(root)
    scan = _scan(root)
    calls: list = []
    _patch_sync(monkeypatch, root, scan)
    _patch_host(monkeypatch, [_response()], calls)
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(json.dumps({"contracts": {}}))
    monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: {"contracts": {}})
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_CATALOG_PATH", catalog_path)

    analyze_service.redecompile_wrapper_receiver({"project": "p", "repo": "r"}, "SQLDbContext")

    assert calls[0][2] is True


def test_valid_selector_does_not_block_explicit_named_redecompile(monkeypatch, tmp_path) -> None:
    """The exact defect this ticket fixes: `sqldbcontext` is already a valid,
    accepted registry entry (as it is for IQCS today), but an explicit,
    named re-decompile request for `SQLDbContext` must still run and, since
    the fresh Contract Fingerprint differs from the stale one on record,
    must create a new, fingerprint-suffixed entry -- never mutate the
    existing `sqldbcontext` entry in place."""
    root = tmp_path / "IQCS"
    root.mkdir()
    csproj = _write_referencing_project(root)
    scan = _scan(root)
    calls: list = []
    _patch_sync(monkeypatch, root, scan)
    _patch_host(monkeypatch, [_response(fingerprint_seed="fresh-real-types")], calls)

    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    original_registry = {"contracts": {"sqldbcontext": _EXISTING_SQLDBCONTEXT_ENTRY}}
    registry_path.write_text(json.dumps(original_registry), encoding="utf-8")
    catalog_path.write_text(
        json.dumps({"systems": [{"system_id": "IQCS", "wrapper_contract": "sqldbcontext"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        analyze_service,
        "load_contract_registry",
        lambda: json.loads(registry_path.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_CATALOG_PATH", catalog_path)

    result = analyze_service.redecompile_wrapper_receiver(
        {"project": "p", "repo": "r"}, "SQLDbContext"
    )

    assert calls == [(csproj, "SQLDbContext", True)]
    assert result["onboarding_status"] == "created"
    (new_name,) = result["contract_names"]
    assert new_name != "sqldbcontext"
    assert new_name.startswith("sqldbcontext-")

    committed_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert committed_registry["contracts"]["sqldbcontext"] == _EXISTING_SQLDBCONTEXT_ENTRY
    assert new_name in committed_registry["contracts"]
    assert (
        committed_registry["contracts"][new_name]["contract_fingerprint"]
        != _EXISTING_SQLDBCONTEXT_ENTRY["contract_fingerprint"]
    )

    # Ticket 01's scope is the registry alone; the catalog's selector is a
    # separate, explicit repoint (ticket 02) this call never performs.
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == {
        "systems": [{"system_id": "IQCS", "wrapper_contract": "sqldbcontext"}]
    }
