"""Preview or explicitly apply a reviewed external-wrapper contract proposal."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service.contract_acceptance import (  # noqa: E402
    ContractAcceptanceError,
    accept_external_wrapper_contract,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or explicitly apply a reviewed external-wrapper contract."
    )
    parser.add_argument(
        "--proposal",
        required=True,
        type=Path,
        help="JSON file containing the reviewed contract proposal",
    )
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--system-id", default="")
    parser.add_argument("--selector", default="")
    parser.add_argument("--scan-root", action="append", default=[])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write validated registry/catalog changes; never creates a git commit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
        if not isinstance(proposal, dict):
            raise ContractAcceptanceError("proposal_invalid", "proposal JSON 必須是 object")
        kwargs = {
            "system_id": args.system_id,
            "requested_selector": args.selector,
            "scan_roots": args.scan_root,
            "apply": args.apply,
        }
        if args.registry is not None:
            kwargs["registry_path"] = args.registry
        if args.catalog is not None:
            kwargs["catalog_path"] = args.catalog
        result = accept_external_wrapper_contract(proposal, **kwargs)
    except ContractAcceptanceError as exc:
        print(
            json.dumps(
                {"code": exc.code, "message": str(exc), "details": list(exc.details)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"code": "proposal_invalid", "message": str(exc)}), file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())