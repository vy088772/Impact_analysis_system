# service/sp_fetcher.py
"""
預存程序（SP）定義擷取（盡力而為）。

給定程式呼叫到的 SP 名稱，優先從本機 SQL 快取（sql_cache_store.py，由
「更新 SQL 快取」指令 /refresh_sql 落地）取得每個 SP 的完整定義（T-SQL 內文）、
參數與引用資料表；快取沒有時才即時連線 SQL Server 補查（安全網，避免使用者
忘記先跑 /refresh_sql 就整個沒資料）。

設計為「盡力而為」：無資料庫設定、無快取、連線失敗時回傳空清單，不丟例外。
"""
from __future__ import annotations

from typing import List, Optional

from .sql_cache_store import load_cached
from code_analyzer.sql_analyzer import estimate_complexity_from_definition, extract_tables_from_definition


def _normalize(name: str) -> str:
    """正規化 SP 名稱以利比對：去除 schema 前綴與方括號、轉小寫。"""
    core = (name or "").strip().replace("[", "").replace("]", "")
    if "." in core:
        core = core.rsplit(".", 1)[-1]
    return core.lower()


def _from_cache(sp_names: List[str], database_alias: Optional[str], max_def_chars: int) -> tuple[List[dict], List[str]]:
    """從本機 SQL 快取查找；回傳 (已找到的定義清單, 快取中找不到的名稱清單)。
    快取本身不存在（從未 /refresh_sql 過）時，全部視為「找不到」交給即時查詢補上。
    """
    if not database_alias:
        return [], sp_names

    cached = load_cached(database_alias)
    if not cached:
        return [], sp_names

    lookup = {_normalize(p["name"]): p for p in cached.get("procedures", [])}
    # 原生依賴關係（sys.sql_expression_dependencies，由 refresh_sql_cli 一次落地，
    # 見 sql_analyzer.get_all_dependencies）已經跟 procedures/views/functions/tables
    # 存在同一份快取裡——這裡直接查表即可，不需要再對 definition 文字跑一次 regex
    # （regex 只在快取本身沒有這支 SP 的原生依賴紀錄時，才當 fallback 用）。
    deps_lookup = {_normalize(k): v for k, v in (cached.get("dependencies", {}) or {}).items()}

    found: List[dict] = []
    missing: List[str] = []
    for raw in sp_names:
        p = lookup.get(_normalize(raw))
        if p is None:
            missing.append(raw)
            continue
        definition = p.get("definition", "") or ""
        dep_entry = deps_lookup.get(_normalize(raw))
        if dep_entry is not None:
            # 原生依賴優先：這支 SP 在快取的 dependencies 裡有紀錄（即使 depends_on
            # 是空清單，也代表原生查詢當初確實有查到這支 SP，只是它沒有引用其他物件）
            tables = sorted(dep_entry.get("depends_on", []))
            dependency_source = "native"
        else:
            # dependencies 裡沒有這支 SP 的紀錄（例如舊快取版本、或原生查詢當初
            # 就查不到），才 fallback 回 regex 對 definition 文字分析
            tables = sorted(extract_tables_from_definition(definition)) if definition else []
            dependency_source = "regex"
        found.append({
            "name": raw,
            "exists": bool(definition),
            "parameters": p.get("parameters", []),
            "tables": tables,
            "dependency_source": dependency_source,
            # 複雜度：純字串靜態分析（見 estimate_complexity_from_definition），
            # 不需要即時連線，可直接對快取的 definition 文字計算，故不再留空。
            "complexity": estimate_complexity_from_definition(definition) if definition else "",
            "definition": definition[:max_def_chars],
            "truncated": len(definition) > max_def_chars,
        })
    return found, missing


def _from_live_query(
    sp_names: List[str],
    database_alias: Optional[str],
    max_def_chars: int,
    db_server: Optional[str] = None,
    db_name: Optional[str] = None,
) -> List[dict]:
    """即時連線 SQL Server 查詢（快取沒有時的補查路徑）。

    優先用明確提供的 db_server/db_name（由 catalog 逐系統提供）建立連線；
    兩者都未提供時才退回舊行為（查 .env 的 DB_DATABASES/database_alias）。
    """
    if not sp_names:
        return []

    try:
        from code_analyzer.sql_analyzer import SQLAnalyzer
        analyzer = SQLAnalyzer(database_alias, server=db_server, database_name=db_name)
    except Exception:
        return []

    if not analyzer.connect():
        return []

    out: List[dict] = []
    seen: set[str] = set()
    try:
        for raw in sp_names:
            key = _normalize(raw)
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                info = analyzer.quick_analyze_sp(raw)
            except Exception:
                continue
            if not getattr(info, "exists", False):
                out.append({
                    "name": raw, "exists": False, "parameters": [],
                    "tables": [], "complexity": "", "definition": "", "truncated": False,
                })
                continue
            definition = info.definition or ""
            truncated = len(definition) > max_def_chars
            out.append({
                "name": raw,
                "exists": True,
                "parameters": list(info.parameters),
                "tables": list(info.referenced_tables),
                "dependency_source": getattr(info, "dependency_source", "regex"),
                "complexity": info.estimated_complexity,
                "definition": definition[:max_def_chars],
                "truncated": truncated,
            })
    finally:
        try:
            analyzer.disconnect()
        except Exception:
            pass
    return out


def fetch_sp_definitions(
    sp_names: List[str],
    database_alias: Optional[str] = None,
    max_def_chars: int = 8000,
    db_server: Optional[str] = None,
    db_name: Optional[str] = None,
) -> List[dict]:
    """回傳每個 SP 的定義摘要清單。

    每筆：{name, exists, parameters, tables, complexity, definition, truncated}
    優先讀本機 SQL 快取（快取版不含 complexity/引用資料表，因為那是 quick_analyze_sp
    才會做的正規表達式分析；如需要可日後從快取的 definition 另外解析）；快取沒有
    的名稱才即時連線補查（需 db_server/db_name，由 catalog 提供）。無資料庫或全部
    失敗時回傳空清單。
    """
    if not sp_names:
        return []

    found, missing = _from_cache(sp_names, database_alias, max_def_chars)
    if missing:
        found.extend(_from_live_query(missing, database_alias, max_def_chars, db_server, db_name))
    return found

