#!/usr/bin/env python3
"""Coverage Report：逐一報出每一個 System 的兩個比例，以及每一筆解不出來的理由。

兩個比例分開報、永遠不合成一個數字：Database Invocation 解出 Executed Procedure
Name 的比例，與解出 Resolved Connection Source 的比例。實測過的五個 repository
卡在相反的地方——有的解不出程序名稱、有的解不出連線來源——合成一個數字只會把
「卡在哪裡」藏起來。

線以下的每一筆都指名理由。一個比例數字本身分不出「解析變好了」與「只是變得有
自信」，所以理由代碼才是讓數字可以被行動的那一半。

這支工具只讀既有的掃描快取，不 clone、不 pull。有 current 快取時直接重用，所以
同一個 System 可以反覆量測而不必重掃；沒有快取時才會掃一次，加 --cached-only
可以連那一次都不做，改成回報 scan_cache_missing。

用法：
    python -m tools.coverage_report --system Y-Docs_TTPUR
    python -m tools.coverage_report --system IQCS --format json --output coverage.json
    python -m tools.coverage_report --root data/repos/.../ETR --cached-only
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import (  # noqa: E402
    load_external_wrapper_contract,
    load_wrapper_review_exclusions,
)
from service import analyze_service, coverage_report, scan_store  # noqa: E402
from service.contract_registry import load_contract_registry  # noqa: E402
from service.system_targets import (  # noqa: E402
    default_spec_rag_root,
    load_system_catalog,
    resolve_system_targets,
    scan_cache_state,
)


def measure_root(
    system_id: str,
    root: Path,
    *,
    configured_contract: str = "",
    cached_only: bool = False,
) -> Dict[str, Any]:
    """Measure one scan root of one System, reusing its cache when one is current."""
    cache_ready, cache_reason = scan_cache_state(root)
    if cached_only and not cache_ready:
        return coverage_report.unmeasured_scan_coverage(root, cache_reason)

    scan = scan_store.get_or_scan(root, refresh=False)
    rated = coverage_report.rate_scan_invocations(
        root,
        scan,
        catalog=analyze_service.load_sp_catalog(system_id),
        external_wrapper_contract=load_external_wrapper_contract(configured_contract),
        contract_registry=load_contract_registry(),
        wrapper_review_exclusions=load_wrapper_review_exclusions(system_id),
        explicit_contract=configured_contract or None,
    )
    return coverage_report.build_scan_coverage(root, scan, rated)


def build_report(
    targets: Iterable[Mapping[str, Any]],
    missing_systems: Iterable[str] = (),
    *,
    cached_only: bool = False,
) -> Dict[str, Any]:
    """Measure every target, one System per row, each System's roots underneath."""
    by_system: "OrderedDict[str, List[Mapping[str, Any]]]" = OrderedDict()
    for target in targets:
        by_system.setdefault(str(target.get("system_id") or ""), []).append(target)

    systems: List[Dict[str, Any]] = []
    for system_id, system_targets in by_system.items():
        scans: List[Dict[str, Any]] = []
        reason = ""
        for target in system_targets:
            root = target.get("root")
            if root is None:
                reason = str(target.get("reason") or "source_root_unresolved")
                continue
            scans.append(
                measure_root(
                    system_id,
                    Path(root),
                    configured_contract=str(target.get("configured_contract") or ""),
                    cached_only=cached_only,
                )
            )
        systems.append(coverage_report.build_system_coverage(system_id, scans, reason=reason))
    return coverage_report.build_coverage_report(systems, missing_systems)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="每一個 System 的兩個解析比例，以及線以下每一筆的理由代碼"
    )
    parser.add_argument(
        "--system",
        dest="system_ids",
        action="append",
        default=[],
        help="system_catalog.json 裡的 system id；可重複指定多個",
    )
    parser.add_argument(
        "--root",
        dest="roots",
        action="append",
        default=[],
        help="本機掃描根目錄；可重複指定多個",
    )
    parser.add_argument(
        "--spec-rag-root",
        default=str(default_spec_rag_root()),
        help="用來解析 system id 的 spec-rag 專案根目錄",
    )
    parser.add_argument(
        "--cached-only",
        action="store_true",
        help="只量測已有 current 快取的掃描根目錄，其餘回報快取狀態而不重掃",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="輸出格式（預設：table）",
    )
    parser.add_argument("--output", help="把 JSON 報告寫到這個檔案")
    args = parser.parse_args()

    if args.system_ids and args.roots:
        parser.error("--system 與 --root 不能同時使用")

    missing_systems: List[str] = []
    if args.roots:
        targets: List[Dict[str, Any]] = [
            {"system_id": Path(root).name or root, "root": Path(root), "configured_contract": ""}
            for root in args.roots
        ]
    else:
        spec_rag_root = Path(args.spec_rag_root)
        systems = load_system_catalog(spec_rag_root)
        if not systems:
            parser.error(f"找不到 system_catalog.json，無法解析 --system：{spec_rag_root}")
        targets, missing_systems = resolve_system_targets(systems, args.system_ids)

    report = build_report(targets, missing_systems, cached_only=args.cached_only)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote {output_path}")
    if args.format == "json":
        print(rendered)
    else:
        print(coverage_report.render_coverage_report_text(report))


if __name__ == "__main__":
    main()
