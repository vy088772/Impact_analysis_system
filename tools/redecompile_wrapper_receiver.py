"""Force a fresh, named re-decompilation of one external wrapper receiver type.

`analyze_service.redecompile_wrapper_receiver()` is the maintainer bypass
ADR-0005/0006 describe: it keeps working even when the target System already
has a valid, accepted `wrapper_contract` selector (unlike a bare refresh,
whose Contract Preflight short-circuits once a selector already resolves --
see `test_valid_selector_never_triggers_decompilation`). Until now it was
only reachable from a Python REPL or a test; this gives it a CLI so a
maintainer can run it directly, e.g. after finding -- as with IQCS's
`sqldbcontext-53e5d16df832` -- that the accepted Contract's Implementation
Snapshot is missing a method the System actually calls (docs/adr/0014).

The command is local-only: syncing the checkout, scanning it, and
decompiling the referenced DLL never touch a live database. It writes at
most one new, fingerprint-suffixed entry to `config/external_wrapper_contracts.json`
(ADR-0006) -- it never mutates an existing entry and never repoints any
System's own selector; that stays a separate, explicit acceptance step.

Examples:
    python -m tools.redecompile_wrapper_receiver --system IQCS --receiver-type SQLDbContext
    python -m tools.redecompile_wrapper_receiver --project "System Dept 1" --repo IQCS --receiver-type SQLDbContext
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service import analyze_service  # noqa: E402
from service.system_targets import default_spec_rag_root, load_system_catalog  # noqa: E402


def resolve_source_for_system(system_id: str, spec_rag_root: Path) -> dict:
    """The `{project, repo, branch, path}` Azure DevOps source for one System.

    Reads the same `system_catalog.json` `azure` field `service.system_targets`
    resolves scan roots from -- {} when the System or its `azure` field is
    missing, never a guess.
    """
    normalized = str(system_id or "").strip()
    for item in load_system_catalog(spec_rag_root):
        if str(item.get("system_id") or "").strip() == normalized:
            azure = item.get("azure")
            return dict(azure) if isinstance(azure, dict) else {}
    return {}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Force a fresh, named re-decompilation of one external wrapper "
            "receiver type, bypassing any already-accepted contract selector."
        )
    )
    parser.add_argument(
        "--receiver-type",
        required=True,
        help="receiver type as it appears in the scan, e.g. SQLDbContext",
    )
    parser.add_argument("--system", default="", help="system id from system_catalog.json")
    parser.add_argument(
        "--project", default="", help="Azure DevOps project; overrides --system lookup"
    )
    parser.add_argument("--repo", default="", help="Azure DevOps repo; overrides --system lookup")
    parser.add_argument("--branch", default="", help="Azure DevOps branch")
    parser.add_argument("--path", default="", help="sub-path within the repo, if any")
    parser.add_argument(
        "--spec-rag-root",
        default=str(default_spec_rag_root()),
        help="llamaindex-spec-rag checkout used to resolve --system",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.project or args.repo:
        source = {
            "project": args.project,
            "repo": args.repo,
            "branch": args.branch,
            "path": args.path,
        }
    elif args.system:
        source = resolve_source_for_system(args.system, Path(args.spec_rag_root))
        if not source:
            print(
                json.dumps(
                    {
                        "code": "system_not_found",
                        "message": (
                            f"system_catalog.json 裡找不到 system_id={args.system!r}，"
                            "或它沒有 azure 欄位。"
                        ),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 2
    else:
        print(
            json.dumps(
                {
                    "code": "source_required",
                    "message": "必須指定 --system，或直接給 --project/--repo。",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    try:
        result = analyze_service.redecompile_wrapper_receiver(source, args.receiver_type)
    except analyze_service.ReDecompileError as exc:
        print(
            json.dumps({"code": exc.code, "message": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
