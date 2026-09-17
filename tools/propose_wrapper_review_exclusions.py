#!/usr/bin/env python3
"""Exclusion Candidate Tool：讀掃描結果和排除清單，提報候選項目給維護者核准。

這支工具只讀。它讀已有的掃描快取和 config/wrapper_review_exclusions.json，從中
挑出兩項規則都沒有處理掉的 unresolved wrapper 呼叫，依 (receiver_type,
method_name) 分組，附上呼叫次數和「有沒有任何 System 曾經解析過這一組」的證據。
維護者從報表就能判斷，不必回去讀原始碼。

工具還會替每個候選項目選一個層級：receiver_type 是空字串或已知的 framework
type，就選 Global Exclusion Tier；其餘選候選項目所屬 System 自己的層級。維護者
只需要確認這個選擇，不必自己決定。

輸出的 registry fragment 跟 config/wrapper_review_exclusions.json 裡每個層級的
陣列同一種形狀，維護者可以直接貼進對應層級，不必調整形狀。

這支工具不寫任何檔案：它從不修改 config/wrapper_review_exclusions.json，跑兩次
也不會讓任何檔案的內容改變。

用法：
    python -m tools.propose_wrapper_review_exclusions --system IQCS
    python -m tools.propose_wrapper_review_exclusions --system IQCS --system STC
    python -m tools.propose_wrapper_review_exclusions --root data/repos/.../ETR --cached-only
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
    DbInvocation,
    known_framework_receiver_types,
    load_external_wrapper_contract,
    load_wrapper_review_exclusions,
)
from service import analyze_service, coverage_report, exclusion_candidates, scan_store  # noqa: E402
from service.contract_registry import load_contract_registry  # noqa: E402
from service.system_targets import (  # noqa: E402
    default_spec_rag_root,
    load_system_catalog,
    resolve_system_targets,
    scan_cache_state,
)


def measure_root_invocations(
    system_id: str,
    root: Path,
    *,
    configured_contract: str = "",
    cached_only: bool = False,
) -> List[DbInvocation]:
    """Rate one scan root's raw wrapper facts, reusing its cache when one is current.

    Returns an empty list, never a report row, for a root this run could not
    measure -- an empty scan and an unmeasured scan both propose no candidate,
    which is the correct outcome either way.
    """
    cache_ready, _cache_reason = scan_cache_state(root)
    if cached_only and not cache_ready:
        return []

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
    invocations: List[DbInvocation] = []
    for file_invocations in rated.values():
        invocations.extend(file_invocations)
    return invocations


def build_report(
    targets: Iterable[Mapping[str, Any]],
    missing_systems: Iterable[str] = (),
    *,
    cached_only: bool = False,
) -> Dict[str, Any]:
    """Measure every target, merge each System's roots, then propose candidates."""
    invocations_by_system: "OrderedDict[str, List[DbInvocation]]" = OrderedDict()
    for target in targets:
        system_id = str(target.get("system_id") or "")
        root = target.get("root")
        if root is None:
            invocations_by_system.setdefault(system_id, [])
            continue
        invocations_by_system.setdefault(system_id, []).extend(
            measure_root_invocations(
                system_id,
                Path(root),
                configured_contract=str(target.get("configured_contract") or ""),
                cached_only=cached_only,
            )
        )

    candidates = exclusion_candidates.propose_exclusion_candidates(
        invocations_by_system,
        known_framework_receiver_types=known_framework_receiver_types(),
    )
    return {
        "candidates": candidates,
        "registry_fragment": exclusion_candidates.render_exclusion_fragment(candidates),
        "missing_systems": sorted({str(item) for item in missing_systems if str(item)}),
    }


def render_report_text(report: Mapping[str, Any]) -> str:
    """One line per candidate, then the pasteable fragment."""
    lines: List[str] = []
    for candidate in report.get("candidates") or []:
        lines.append(
            f"{candidate['tier']}  {candidate['receiver_type']!r}.{candidate['method_name']}  "
            f"calls={candidate['call_count']}  "
            f"resolved_elsewhere={candidate['resolved_elsewhere']}  "
            f"(seen in {', '.join(candidate['systems'])})"
        )
    if not report.get("candidates"):
        lines.append("no exclusion candidates")
    for system_id in report.get("missing_systems") or []:
        lines.append(f"unknown system: {system_id}")
    lines.append("")
    lines.append("registry fragment (paste each tier's list into config/wrapper_review_exclusions.json):")
    lines.append(json.dumps(report.get("registry_fragment") or {}, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="讀掃描結果和排除清單，提報 Exclusion Candidate 給維護者核准（只讀，不寫）"
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
        help="只量測已有 current 快取的掃描根目錄，其餘不計入候選",
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
        print(render_report_text(report))


if __name__ == "__main__":
    main()
