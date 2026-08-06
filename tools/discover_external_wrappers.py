"""Discover wrapper calls from existing StaticAnalyzerHost scan caches.

The command is intentionally read-only. It does not clone repositories, pull
branches, or create scan caches. Refresh source caches first when a system is
missing or stale, then run this command to review newly observed wrappers.

Examples:
    python -m tools.discover_external_wrappers
    python -m tools.discover_external_wrappers --system Y-Docs_TTPUR
    python -m tools.discover_external_wrappers --system Y-Docs_TTPUR --format json
    python -m tools.discover_external_wrappers --root data/repos/.../TTPUR
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import (  # noqa: E402
    external_wrapper_contract_candidates,
    load_external_wrapper_contract,
)
from config.settings import settings  # noqa: E402
from service import repo_manager, scan_store  # noqa: E402


def _default_spec_rag_root() -> Path:
    return Path(settings.AZURE_CLONE_ROOT).resolve().parent.parent.parent / "llamaindex-spec-rag"


def _load_catalog(spec_rag_root: Path) -> List[dict]:
    catalog_path = spec_rag_root / "catalog" / "system_catalog.json"
    if not catalog_path.exists():
        return []
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    systems = payload.get("systems", [])
    return [item for item in systems if isinstance(item, dict)] if isinstance(systems, list) else []


def _catalog_targets(
    systems: Iterable[dict],
    requested_systems: Iterable[str],
) -> Tuple[List[dict], List[str]]:
    by_id = {
        str(item.get("system_id") or "").strip(): item
        for item in systems
        if str(item.get("system_id") or "").strip()
    }
    requested = [str(item).strip() for item in requested_systems if str(item).strip()]
    selected = requested or list(by_id)
    targets: List[dict] = []
    not_found: List[str] = []
    for system_id in selected:
        item = by_id.get(system_id)
        if item is None:
            not_found.append(system_id)
            continue
        azure = item.get("azure") or {}
        if not isinstance(azure, dict):
            azure = {}
        roots = repo_manager.peek_scan_roots(azure)
        if not roots:
            targets.append(
                {
                    "system_id": system_id,
                    "root": None,
                    "configured_contract": str(item.get("wrapper_contract") or ""),
                    "reason": "source_root_unresolved",
                }
            )
            continue
        for root in roots:
            targets.append(
                {
                    "system_id": system_id,
                    "root": Path(root),
                    "configured_contract": str(item.get("wrapper_contract") or ""),
                }
            )
    return targets, not_found


def _cached_targets() -> List[dict]:
    cache_root = Path(settings.SCAN_CACHE_ROOT)
    targets: List[dict] = []
    for meta_path in sorted(cache_root.glob("*.meta.json")):
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            root_value = str(metadata.get("root") or "").strip()
        except (OSError, json.JSONDecodeError):
            continue
        if not root_value:
            continue
        targets.append(
            {
                "system_id": Path(root_value).name or root_value,
                "root": Path(root_value),
                "configured_contract": "",
            }
        )
    return targets


def _dedupe_targets(targets: Iterable[dict]) -> List[dict]:
    unique: OrderedDict[tuple[str, str], dict] = OrderedDict()
    for target in targets:
        root = target.get("root")
        root_key = str(Path(root).resolve()).casefold() if root else ""
        key = (str(target.get("system_id") or ""), root_key)
        unique.setdefault(key, target)
    return list(unique.values())


def _relative_path(source_file: str, project_root: str) -> str:
    path = Path(source_file)
    try:
        return path.resolve().relative_to(Path(project_root).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _method_contract(
    contract: Optional[Mapping[str, Any]],
    method_name: str,
) -> Optional[Mapping[str, Any]]:
    if contract is None:
        return None
    methods = contract.get("methods", {})
    if not isinstance(methods, Mapping):
        return None
    folded_name = method_name.casefold()
    for name, value in methods.items():
        if str(name).casefold() == folded_name and isinstance(value, Mapping):
            return value
    return None


def _receiver_matches(contract: Mapping[str, Any], receiver_type: str) -> bool:
    receiver_types = contract.get("receiver_types", [])
    if not receiver_type or not isinstance(receiver_types, list):
        return True
    normalized = receiver_type.split(".")[-1].casefold()
    return any(
        normalized == str(candidate).split(".")[-1].casefold()
        for candidate in receiver_types
    )


def _classify_wrapper(
    record: Mapping[str, Any],
    configured_contract_name: str = "",
) -> Dict[str, Any]:
    method_name = str(record.get("wrapper_method_name") or "").strip()
    receiver_type = str(record.get("wrapper_receiver_type") or "").strip()
    source_available = record.get("wrapper_source_available") is True

    if source_available:
        return {
            "wrapper_kind": "source_wrapper",
            "status": "source_wrapper",
            "selection_source": "source_code",
            "contract": "",
            "contract_mode": str(record.get("wrapper_mode") or ""),
            "contract_sink": "",
            "candidate_contracts": [],
            "reason": "",
        }

    configured_name = str(configured_contract_name or "").strip()
    if configured_name:
        configured = load_external_wrapper_contract(configured_name)
        candidates = [configured] if configured is not None else []
        selection_source = "system_catalog"
        if configured is None:
            return {
                "wrapper_kind": "external_wrapper",
                "status": "unresolved_contract",
                "selection_source": selection_source,
                "contract": "",
                "contract_mode": "",
                "contract_sink": "",
                "candidate_contracts": [configured_name],
                "reason": "configured_contract_not_found",
            }
    else:
        candidates = external_wrapper_contract_candidates(receiver_type)
        selection_source = "auto_receiver_type"

    candidate_names = [str(contract.get("name") or "") for contract in candidates]
    if len(candidates) > 1:
        return {
            "wrapper_kind": "external_wrapper",
            "status": "ambiguous_contract",
            "selection_source": "ambiguous_receiver_type",
            "contract": "",
            "contract_mode": "",
            "contract_sink": "",
            "candidate_contracts": candidate_names,
            "reason": "multiple_contracts_match_receiver_type",
        }
    if not candidates:
        return {
            "wrapper_kind": "external_wrapper",
            "status": "unresolved_contract",
            "selection_source": "unresolved_receiver_type",
            "contract": "",
            "contract_mode": "",
            "contract_sink": "",
            "candidate_contracts": [],
            "reason": "receiver_type_missing" if not receiver_type else "no_contract_matches_receiver_type",
        }

    contract = candidates[0]
    contract_name = str(contract.get("name") or configured_name)
    if not _receiver_matches(contract, receiver_type):
        return {
            "wrapper_kind": "external_wrapper",
            "status": "receiver_mismatch",
            "selection_source": selection_source,
            "contract": contract_name,
            "contract_mode": "",
            "contract_sink": "",
            "candidate_contracts": candidate_names,
            "reason": "receiver_type_does_not_match_contract",
        }

    method_contract = _method_contract(contract, method_name)
    if method_contract is None:
        return {
            "wrapper_kind": "external_wrapper",
            "status": "unresolved_method",
            "selection_source": selection_source,
            "contract": contract_name,
            "contract_mode": "",
            "contract_sink": "",
            "candidate_contracts": candidate_names,
            "reason": "method_not_in_contract",
        }

    return {
        "wrapper_kind": "external_wrapper",
        "status": "explicit_selected" if configured_name else "auto_selected",
        "selection_source": "system_catalog" if configured_name else selection_source,
        "contract": contract_name,
        "contract_mode": str(method_contract.get("mode") or ""),
        "contract_sink": str(method_contract.get("sink") or ""),
        "candidate_contracts": candidate_names,
        "reason": "",
    }


def _is_wrapper_record(record: Mapping[str, Any]) -> bool:
    invocation_kind = str(record.get("invocation_kind") or "").casefold()
    return invocation_kind == "source_wrapper" or bool(
        str(record.get("wrapper_method_name") or "").strip()
        or str(record.get("wrapper_receiver_type") or "").strip()
    )


def _location(record: Mapping[str, Any], source_file: str, project_root: str) -> Dict[str, Any]:
    command_text = record.get("command_text")
    return {
        "file": _relative_path(source_file, project_root),
        "line": int(record.get("line_number") or 0),
        "start_offset": int(record.get("start_offset") or 0),
        "end_offset": int(record.get("end_offset") or 0),
        "command_text_kind": str(record.get("command_text_kind") or ""),
        "command_text": str(command_text) if command_text is not None else "",
        "wrapper_mode": str(record.get("wrapper_mode") or ""),
    }


def _cache_state(root: Path) -> Tuple[bool, str]:
    if scan_store.has_cache(root):
        return True, ""

    cache_root = Path(settings.SCAN_CACHE_ROOT)
    resolved_root = str(root.resolve()).casefold()
    for meta_path in cache_root.glob("*.meta.json"):
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cached_root = str(metadata.get("root") or "").strip()
        if not cached_root or cached_root.casefold() != resolved_root:
            continue
        if metadata.get("cache_version") != getattr(scan_store, "_CACHE_VERSION", None):
            return False, "scan_cache_stale"
        if meta_path.with_suffix("").with_suffix(".pkl").exists():
            return False, "scan_cache_invalid"
        return False, "scan_cache_missing"
    return False, "scan_cache_missing"


def _scan_report(
    system_id: str,
    root: Path,
    configured_contract_name: str = "",
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    cache_ready, cache_reason = _cache_state(root)
    if not cache_ready:
        return (
            {
                "system_id": system_id,
                "root": str(root),
                "cache": False,
                "wrapper_calls": 0,
                "reason": cache_reason,
            },
            [],
        )

    scan = scan_store.get_or_scan(root, refresh=False)
    groups: OrderedDict[tuple, Dict[str, Any]] = OrderedDict()
    wrapper_calls = 0
    for source_file, records in getattr(scan, "db_invocations", {}).items():
        for record in records or []:
            if not isinstance(record, Mapping) or not _is_wrapper_record(record):
                continue
            wrapper_calls += 1
            classification = _classify_wrapper(record, configured_contract_name)
            wrapper_class = str(record.get("wrapper_class_name") or "").strip()
            receiver_type = str(record.get("wrapper_receiver_type") or "").strip()
            method_name = str(record.get("wrapper_method_name") or "").strip()
            group_key = (
                wrapper_class,
                receiver_type,
                method_name,
                classification["wrapper_kind"],
                classification["status"],
                classification["contract"],
                classification["reason"],
            )
            group = groups.get(group_key)
            if group is None:
                group = {
                    "system_id": system_id,
                    "root": str(root),
                    "wrapper_class": wrapper_class,
                    "receiver_type": receiver_type,
                    "wrapper_method": method_name,
                    **classification,
                    "calls": 0,
                    "locations": [],
                }
                groups[group_key] = group
            group["calls"] += 1
            group["locations"].append(_location(record, source_file, str(root)))

    summary = {
        "system_id": system_id,
        "root": str(root),
        "cache": True,
        "wrapper_calls": wrapper_calls,
        "groups": len(groups),
    }
    return summary, list(groups.values())


def build_report(targets: Iterable[dict], missing_systems: Iterable[str] = ()) -> Dict[str, Any]:
    summaries: List[Dict[str, Any]] = []
    observations: List[Dict[str, Any]] = []
    for target in _dedupe_targets(targets):
        root = target.get("root")
        if root is None:
            summaries.append(
                {
                    "system_id": str(target.get("system_id") or ""),
                    "root": "",
                    "cache": False,
                    "wrapper_calls": 0,
                    "reason": str(target.get("reason") or "source_root_unresolved"),
                }
            )
            continue
        summary, groups = _scan_report(
            str(target.get("system_id") or ""),
            Path(root),
            str(target.get("configured_contract") or ""),
        )
        summaries.append(summary)
        observations.extend(groups)

    observations.sort(
        key=lambda item: (
            item["system_id"].casefold(),
            item["receiver_type"].casefold(),
            item["wrapper_method"].casefold(),
            item["status"],
        )
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scans": summaries,
        "observations": observations,
        "missing_systems": sorted(set(str(item) for item in missing_systems if str(item))),
        "totals": {
            "systems": len({item["system_id"] for item in summaries}),
            "cached_scans": sum(1 for item in summaries if item.get("cache")),
            "wrapper_calls": sum(item["wrapper_calls"] for item in summaries),
            "observation_groups": len(observations),
            "auto_selected": sum(item["status"] == "auto_selected" for item in observations),
            "unresolved": sum(
                item["status"] in {"ambiguous_contract", "unresolved_contract", "unresolved_method", "receiver_mismatch"}
                for item in observations
            ),
        },
    }


def _truncate(value: object, limit: int = 42) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _print_table(report: Mapping[str, Any]) -> None:
    observations = list(report.get("observations") or [])
    headers = ["system", "receiver", "method", "status", "contract", "calls", "reason"]
    rows = [
        [
            _truncate(item.get("system_id"), 22),
            _truncate(item.get("receiver_type"), 22),
            _truncate(item.get("wrapper_method"), 24),
            _truncate(item.get("status"), 18),
            _truncate(item.get("contract"), 18),
            str(item.get("calls", 0)),
            _truncate(item.get("reason"), 38),
        ]
        for item in observations
    ]
    widths = [
        max([len(headers[index]), *(len(row[index]) for row in rows)])
        for index in range(len(headers))
    ]

    def render(values: List[str]) -> str:
        return " | ".join(value.ljust(widths[index]) for index, value in enumerate(values))

    print(render(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(render(row))
    totals = report.get("totals") or {}
    print(
        "\nscans={scans} cached={cached} wrapper_calls={calls} groups={groups} "
        "auto_selected={auto} unresolved={unresolved}".format(
            scans=totals.get("systems", 0),
            cached=totals.get("cached_scans", 0),
            calls=totals.get("wrapper_calls", 0),
            groups=totals.get("observation_groups", 0),
            auto=totals.get("auto_selected", 0),
            unresolved=totals.get("unresolved", 0),
        )
    )
    missing = [item for item in report.get("scans", []) if not item.get("cache")]
    if missing:
        print("\ncache not ready:")
        for item in missing:
            print(f"- {item.get('system_id')}: {item.get('reason')} ({item.get('root')})")
    if report.get("missing_systems"):
        print(f"\nunknown systems: {', '.join(report['missing_systems'])}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover external and source wrapper calls from read-only scan caches."
    )
    parser.add_argument(
        "--system",
        dest="system_ids",
        action="append",
        default=[],
        help="system id from system_catalog.json; repeat for multiple systems",
    )
    parser.add_argument(
        "--root",
        dest="roots",
        action="append",
        default=[],
        help="local scan root; repeat for multiple roots",
    )
    parser.add_argument(
        "--spec-rag-root",
        default=str(_default_spec_rag_root()),
        help="spec-rag project root used to resolve system ids",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="output format (default: table)",
    )
    parser.add_argument("--output", help="write the JSON report to this file")
    args = parser.parse_args()

    if args.system_ids and args.roots:
        parser.error("--system and --root cannot be combined")

    missing_systems: List[str] = []
    if args.roots:
        targets = [
            {"system_id": Path(root).name or root, "root": Path(root), "configured_contract": ""}
            for root in args.roots
        ]
    else:
        spec_rag_root = Path(args.spec_rag_root)
        systems = _load_catalog(spec_rag_root)
        if systems:
            targets, missing_systems = _catalog_targets(systems, args.system_ids)
        elif args.system_ids:
            parser.error(f"找不到 system_catalog.json，無法解析 --system：{spec_rag_root}")
        else:
            targets = _cached_targets()

    report = build_report(targets, missing_systems)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote {output_path}")
    if args.format == "json":
        print(rendered)
    else:
        _print_table(report)


if __name__ == "__main__":
    main()