"""Ticket 03 (accepted-contract-resolves-its-calls): the Contract migration that adds a
missing Delegation Alias collection to Contracts already in the registry.

The decompiler has always found a Delegated Method and recorded it in the decompilation
cache; it never wrote that finding into a Contract already accepted before this ticket. The
migration in `service/contract_migrations.py` reads the cached decompilation result -- it
never re-decompiles an assembly -- and derives a Delegation Alias for each Delegated Method,
flattening any chain to the operation that performs the work (ADR-0027).

Three things this narrow seam must prove, per the spec's own Testing Decisions: the aliases
arrive, a two-step chain flattens to its final target, and the Contract Fingerprint stays
byte-identical before and after -- the fingerprint assertion guards the cross-System reuse
promise a Delegation Alias must never break.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.external_wrapper_contracts import (
    compute_contract_fingerprint,
    flatten_delegation_aliases,
)
from service.contract_migrations import add_delegation_aliases_from_decompilation_cache


_ASSEMBLY_IDENTITY = "deadbeef" * 8
_RECEIVER_TYPE = "SQLDbContext"

# The real three delegations, byte-identical to what `WrapperDecompiler.cs` reports for
# `CommonLibrary.dll`'s `SQLDbContext`: a two-step chain, and a separate one-step chain.
_DELEGATED_METHODS = [
    {
        "method_identity": "SQLDbContext.usp_ExecCmdGetFisrtValueAsync(string,Microsoft.EntityFrameworkCore.SqlParameter[]?,bool)",
        "delegates_to": "usp_ExecCmdGetDataTableAsync",
    },
    {
        "method_identity": "SQLDbContext.usp_ExecCmdGetDataTableAsync(string,Microsoft.EntityFrameworkCore.SqlParameter[]?,bool)",
        "delegates_to": "usp_ExecCmdGetDataSetAsync",
    },
    {
        "method_identity": "SQLDbContext.usp_ExecCmdGetJsonObjectAsync(string,Microsoft.EntityFrameworkCore.SqlParameter[]?,bool)",
        "delegates_to": "usp_ExecCmdGetJsonObjectListAsync",
    },
]


def _write_decompilation_cache(cache_dir: Path, *, delegated_methods: object) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    document = {
        "cache_version": 1,
        "assembly_identity": _ASSEMBLY_IDENTITY,
        "attempts": {
            _RECEIVER_TYPE: {
                "saved_at": 0,
                "host_identity": "host",
                "response": {
                    "status": "resolved",
                    "delegated_methods": delegated_methods,
                },
            }
        },
    }
    (cache_dir / f"{_ASSEMBLY_IDENTITY}.json").write_text(
        json.dumps(document), encoding="utf-8"
    )


def _behavior_signature() -> dict:
    return {
        "signature_version": "contract-behavior-v1",
        "operations": [
            {
                "operation_identity": "sqldbcontext.usp_execcmdgetdatasetasync(string,bool)",
                "method_identity": "sqldbcontext.usp_execcmdgetdatasetasync(string,bool)",
                "method_name": "usp_execcmdgetdatasetasync",
                "method_arity": 2,
                "required_parameter_count": 1,
                "parameter_types": ["string", "bool"],
                "argument_roles": {"command_text": 0, "command_type": 1},
                "effective_command_semantics": "call_site",
                "terminal_sink": "ExecuteReaderAsync",
                "connection_behavior_boundary": "context_connection",
                "branch_rules": [],
            }
        ],
    }


def _accepted_contract_without_aliases() -> dict:
    return {
        "receiver_types": ["SQLDbContext"],
        "methods": {
            "usp_ExecCmdGetDataSetAsync": {
                "mode": "call_site",
                "sink": "ExecuteReaderAsync",
            },
        },
        "behavior_signature": _behavior_signature(),
        "contract_fingerprint": compute_contract_fingerprint(
            {"behavior_surface": _behavior_signature()}
        ),
        "signature_version": "contract-behavior-v1",
        "status": "accepted",
        "lifecycle": {"status": "accepted", "revision": 1},
        "implementation_snapshots": [
            {
                "assembly_identity": _ASSEMBLY_IDENTITY,
                "behavior_surface_unit": _RECEIVER_TYPE,
            }
        ],
    }


def test_the_migration_adds_the_flattened_aliases_from_the_cached_decompilation_result(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "decompilation_cache"
    _write_decompilation_cache(cache_dir, delegated_methods=_DELEGATED_METHODS)
    registry = {"contracts": {"sqldbcontext": _accepted_contract_without_aliases()}}

    after, report = add_delegation_aliases_from_decompilation_cache(
        registry, decompilation_cache_dir=cache_dir
    )

    assert report == [
        {
            "contract": "sqldbcontext",
            "action": "added",
            "aliases": flatten_delegation_aliases(_DELEGATED_METHODS),
        }
    ]
    aliases = after["contracts"]["sqldbcontext"]["delegation_aliases"]
    # The two-step chain flattens: an alias always points at the operation that performs the
    # work, never at another alias.
    assert aliases["usp_ExecCmdGetFisrtValueAsync"] == "usp_ExecCmdGetDataSetAsync"
    assert aliases["usp_ExecCmdGetDataTableAsync"] == "usp_ExecCmdGetDataSetAsync"
    assert aliases["usp_ExecCmdGetJsonObjectAsync"] == "usp_ExecCmdGetJsonObjectListAsync"


def test_the_migration_never_changes_the_contract_fingerprint(tmp_path: Path) -> None:
    """ADR-0027's guarantee: the alias collection sits outside the behaviour signature, so a
    System that already matched this Contract by fingerprint keeps reusing it."""
    cache_dir = tmp_path / "decompilation_cache"
    _write_decompilation_cache(cache_dir, delegated_methods=_DELEGATED_METHODS)
    before_contract = _accepted_contract_without_aliases()
    registry = {"contracts": {"sqldbcontext": before_contract}}

    after, _ = add_delegation_aliases_from_decompilation_cache(
        registry, decompilation_cache_dir=cache_dir
    )

    after_contract = after["contracts"]["sqldbcontext"]
    assert after_contract["delegation_aliases"]
    assert after_contract["contract_fingerprint"] == before_contract["contract_fingerprint"]
    assert after_contract["behavior_signature"] == before_contract["behavior_signature"]


def test_the_migration_walks_every_contract_and_leaves_one_with_no_delegation_unchanged(
    tmp_path: Path,
) -> None:
    """`SQLFunc` and `SQLObject` carry no delegation today: the migration must not invent one,
    and the entry that carries an explicit empty `delegated_methods` list stays untouched."""
    cache_dir = tmp_path / "decompilation_cache"
    _write_decompilation_cache(cache_dir, delegated_methods=_DELEGATED_METHODS)

    no_delegation_assembly = "cafebabe" * 8
    (cache_dir / f"{no_delegation_assembly}.json").write_text(
        json.dumps(
            {
                "cache_version": 1,
                "assembly_identity": no_delegation_assembly,
                "attempts": {
                    "SQLFunc": {
                        "saved_at": 0,
                        "host_identity": "host",
                        "response": {"status": "resolved", "delegated_methods": []},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    no_delegation_contract = _accepted_contract_without_aliases()
    no_delegation_contract["implementation_snapshots"] = [
        {"assembly_identity": no_delegation_assembly, "behavior_surface_unit": "SQLFunc"}
    ]
    registry = {
        "contracts": {
            "sqldbcontext": _accepted_contract_without_aliases(),
            "sqlfunc": no_delegation_contract,
        }
    }

    after, report = add_delegation_aliases_from_decompilation_cache(
        registry, decompilation_cache_dir=cache_dir
    )

    actions = {item["contract"]: item["action"] for item in report}
    assert actions["sqldbcontext"] == "added"
    assert actions["sqlfunc"] == "skipped_no_delegations"
    assert "delegation_aliases" not in after["contracts"]["sqlfunc"]


def test_a_contract_that_already_carries_aliases_is_left_alone(tmp_path: Path) -> None:
    cache_dir = tmp_path / "decompilation_cache"
    _write_decompilation_cache(cache_dir, delegated_methods=_DELEGATED_METHODS)
    contract = _accepted_contract_without_aliases()
    contract["delegation_aliases"] = {"already": "there"}
    registry = {"contracts": {"sqldbcontext": contract}}

    after, report = add_delegation_aliases_from_decompilation_cache(
        registry, decompilation_cache_dir=cache_dir
    )

    assert report == [{"contract": "sqldbcontext", "action": "skipped_already_present"}]
    assert after["contracts"]["sqldbcontext"]["delegation_aliases"] == {"already": "there"}


def test_a_stale_cache_missing_the_delegated_methods_key_is_not_treated_as_zero_delegations(
    tmp_path: Path,
) -> None:
    """An old cache written before the decompiler recorded delegation at all must not be read
    as "no delegation" -- an absent key is not evidence of that (ADR-0029's "absence proves
    nothing" rule applies here too)."""
    cache_dir = tmp_path / "decompilation_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{_ASSEMBLY_IDENTITY}.json").write_text(
        json.dumps(
            {
                "cache_version": 1,
                "assembly_identity": _ASSEMBLY_IDENTITY,
                "attempts": {
                    _RECEIVER_TYPE: {
                        "saved_at": 0,
                        "host_identity": "host",
                        "response": {"status": "resolved"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    registry = {"contracts": {"sqldbcontext": _accepted_contract_without_aliases()}}

    after, report = add_delegation_aliases_from_decompilation_cache(
        registry, decompilation_cache_dir=cache_dir
    )

    assert report == [{"contract": "sqldbcontext", "action": "skipped_stale_cache_schema"}]
    assert "delegation_aliases" not in after["contracts"]["sqldbcontext"]
