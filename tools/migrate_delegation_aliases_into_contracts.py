"""Add missing Delegation Aliases to Contracts already in the registry.

Reads each Contract's cached decompilation result (never re-decompiling any
assembly) and derives a Delegation Alias for every Delegated Method the
decompiler found. Walks every Contract in the registry, not one named
Contract. See ``service/contract_migrations.py`` for the pure logic this CLI
wraps, and ADR-0027 for why this never changes a Contract Fingerprint.

Usage:
    python tools/migrate_delegation_aliases_into_contracts.py [--dry-run] [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service.contract_migrations import (  # noqa: E402
    DEFAULT_DECOMPILATION_CACHE_DIR,
    add_delegation_aliases_from_decompilation_cache,
)
from service.contract_registry import DEFAULT_REGISTRY_PATH, load_contract_registry  # noqa: E402
from service.contract_transaction import (  # noqa: E402
    ContractTransactionError,
    commit_staged_contract_transaction,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add missing Delegation Aliases to Contracts already in the registry"
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument(
        "--decompilation-cache",
        type=Path,
        default=DEFAULT_DECOMPILATION_CACHE_DIR,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the staged registry; without it this only previews the report",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    registry_payload = load_contract_registry(args.registry, strict=True)
    after_payload, report = add_delegation_aliases_from_decompilation_cache(
        registry_payload,
        decompilation_cache_dir=args.decompilation_cache,
    )

    result: dict[str, object] = {"report": report, "applied": False}
    if args.apply and any(item["action"] == "added" for item in report):
        try:
            commit_result = commit_staged_contract_transaction(
                staged_registry=after_payload,
                trigger="contract_migration",
                registry_path=args.registry,
            )
        except ContractTransactionError as exc:
            print(
                json.dumps(
                    {"code": exc.code, "message": str(exc), "details": list(exc.details)},
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 2
        result["applied"] = True
        result["transaction_id"] = commit_result["transaction_id"]
        result["manifest_path"] = commit_result["manifest_path"]
        result["written_files"] = commit_result["written_files"]

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
