"""CLI glue for `analyze_service.redecompile_wrapper_receiver()`.

`redecompile_wrapper_receiver()` itself is covered end-to-end by
`test_redecompile_wrapper_receiver.py`; these tests cover only what this
module adds on top of it -- turning `--system`/`--project`+`--repo` into the
`{project, repo, branch, path}` source dict the service function expects,
and turning its result/`ReDecompileError` into a process exit code and JSON
on stdout/stderr, the same convention `accept_external_wrapper_contract.py`
uses.
"""
from __future__ import annotations

import json

import pytest

import tools.redecompile_wrapper_receiver as cli
from service import analyze_service


def _write_catalog(tmp_path, systems):
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / "system_catalog.json").write_text(
        json.dumps({"systems": systems}), encoding="utf-8"
    )
    return tmp_path


def test_resolve_source_for_system_reads_azure_field(tmp_path) -> None:
    spec_rag_root = _write_catalog(
        tmp_path,
        [
            {
                "system_id": "IQCS",
                "azure": {"project": "System Dept 1", "repo": "IQCS", "branch": "", "path": ""},
            }
        ],
    )

    source = cli.resolve_source_for_system("IQCS", spec_rag_root)

    assert source == {"project": "System Dept 1", "repo": "IQCS", "branch": "", "path": ""}


def test_resolve_source_for_system_unknown_id_returns_empty(tmp_path) -> None:
    spec_rag_root = _write_catalog(tmp_path, [{"system_id": "TTPUR", "azure": {"repo": "TTPUR"}}])

    assert cli.resolve_source_for_system("IQCS", spec_rag_root) == {}


def test_main_resolves_system_and_forwards_to_service(monkeypatch, tmp_path, capsys) -> None:
    spec_rag_root = _write_catalog(
        tmp_path,
        [
            {
                "system_id": "IQCS",
                "azure": {"project": "System Dept 1", "repo": "IQCS", "branch": "", "path": ""},
            }
        ],
    )
    calls: list[tuple[dict, str]] = []

    def fake_redecompile(source: dict, receiver_type: str) -> dict:
        calls.append((source, receiver_type))
        return {"receiver_type": receiver_type, "onboarding_status": "created"}

    monkeypatch.setattr(analyze_service, "redecompile_wrapper_receiver", fake_redecompile)

    exit_code = cli.main(
        [
            "--system",
            "IQCS",
            "--receiver-type",
            "SQLDbContext",
            "--spec-rag-root",
            str(spec_rag_root),
        ]
    )

    assert exit_code == 0
    assert calls == [
        ({"project": "System Dept 1", "repo": "IQCS", "branch": "", "path": ""}, "SQLDbContext")
    ]
    printed = json.loads(capsys.readouterr().out)
    assert printed == {"receiver_type": "SQLDbContext", "onboarding_status": "created"}


def test_main_project_repo_override_skips_catalog_lookup(monkeypatch, capsys) -> None:
    calls: list[tuple[dict, str]] = []
    monkeypatch.setattr(
        analyze_service,
        "redecompile_wrapper_receiver",
        lambda source, receiver_type: calls.append((source, receiver_type)) or {"ok": True},
    )

    exit_code = cli.main(
        [
            "--project",
            "System Dept 1",
            "--repo",
            "IQCS",
            "--receiver-type",
            "SQLDbContext",
        ]
    )

    assert exit_code == 0
    assert calls == [
        ({"project": "System Dept 1", "repo": "IQCS", "branch": "", "path": ""}, "SQLDbContext")
    ]


def test_main_unknown_system_fails_without_calling_service(monkeypatch, tmp_path, capsys) -> None:
    spec_rag_root = _write_catalog(tmp_path, [{"system_id": "TTPUR", "azure": {"repo": "TTPUR"}}])
    calls: list = []
    monkeypatch.setattr(
        analyze_service,
        "redecompile_wrapper_receiver",
        lambda *a, **k: calls.append((a, k)) or {},
    )

    exit_code = cli.main(
        [
            "--system",
            "IQCS",
            "--receiver-type",
            "SQLDbContext",
            "--spec-rag-root",
            str(spec_rag_root),
        ]
    )

    assert exit_code == 2
    assert calls == []
    error = json.loads(capsys.readouterr().err)
    assert error["code"] == "system_not_found"


def test_main_requires_a_source(capsys) -> None:
    exit_code = cli.main(["--receiver-type", "SQLDbContext"])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["code"] == "source_required"


def test_main_reports_redecompile_error_on_stderr(monkeypatch, capsys) -> None:
    def _raise(source: dict, receiver_type: str) -> dict:
        raise analyze_service.ReDecompileError("csproj_not_found", "找不到 .csproj")

    monkeypatch.setattr(analyze_service, "redecompile_wrapper_receiver", _raise)

    exit_code = cli.main(
        ["--project", "System Dept 1", "--repo", "IQCS", "--receiver-type", "SQLDbContext"]
    )

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error == {"code": "csproj_not_found", "message": "找不到 .csproj"}
