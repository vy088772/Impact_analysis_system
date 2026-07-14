# service/flow_chain_builder.py
"""
變更影響「關係鏈」建構（無 AI）。

把既有的靜態分析關聯（方法呼叫鏈、C#到SP關聯、C#到資料表關聯、View 層控制項
事件、SP 內部巢狀呼叫、SP 引用資料表、FK 連動表）串成結構化的候選鏈，交給
呼叫端（spec-rag 的 mode 3 agent）自行判斷哪一條鏈才是使用者實際要問的那個——
這裡只負責把鏈算出來，不做任何「這條鏈跟問題相不相關」的判斷。

兩種方向：
  - forward（build_forward_chain）：從指定的錨點方法（通常是 spec-rag 端依
    UI 動作用語意檢索，從 ui_fields 的 events 挑出的候選 handler 方法名稱）出發，
    走方法呼叫鏈，再到直接呼叫的 SP，再遞迴展開 SP 內部呼叫的其他 SP，最後彙整
    各層 SP 引用的資料表（含 FK 連動表）。
  - backward（build_backward_chains）：從指定的資料表（可選：欄位名稱）出發，
    反查哪些 SP 引用了這張表，再反查哪些 C# 方法呼叫了這些 SP（或直接用 SQL
    存取這張表），最後反查哪個 UI 控制項事件會觸發這個方法。

已知限制（誠實標注，不假裝是保證）：
  - 欄位（column）層級的比對是「SP 定義文字裡有沒有出現這個欄位名稱字串」的
    近似值（文字比對），不是解析 SQL 語法樹後的結構化保證，可能有誤判
    （欄位名稱剛好也是變數名或其他表的欄位名）。
  - SP 呼叫 SP（sp_call_fetcher）、SP 引用資料表（sql_analyzer 的
    extract_tables_from_definition）都只讀本機 SQL 快取，快取不存在時該層
    直接留空，不觸發即時資料庫連線（與這個專案其餘「盡力而為」的設計一致）。
  - UI 控制項事件反查是用「同目錄同檔名，.aspx.cs 對應 .aspx」的 WebForms
    命名慣例配對 code-behind 與 aspx 檔案，非 WebForms 專案（無對應 .aspx）
    這段會自然找不到、留空，不影響其餘鏈的建構。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from code_analyzer.models import FileAnalysisResult
from code_analyzer.sql_analyzer import extract_tables_from_definition
from .sql_cache_store import load_cached
from .sp_fetcher import fetch_sp_definitions
from .sp_call_fetcher import fetch_called_sp_names
from .fk_resolver import resolve_fk_related

_MAX_SP_DEPTH_HARD_CAP = 5  # 無論呼叫端傳入多大，都不超過這個層數，避免巨大 SP 網絡失控展開


def _normalize_name(name: str) -> str:
    """去除中括號、schema 前綴、轉小寫；SP 名稱與資料表名稱共用同一套正規化規則。"""
    core = (name or "").strip().replace("[", "").replace("]", "")
    if "." in core:
        core = core.rsplit(".", 1)[-1]
    return core.lower()


def _rel(file_path: str, root: Path) -> str:
    try:
        return str(Path(file_path).resolve().relative_to(root.resolve()))
    except Exception:
        return file_path


# ─────────────────────────────────────────────────────────────────────────────
# 正向鏈：錨點方法 -> 呼叫鏈 -> SP -> SP -> 資料表
# ─────────────────────────────────────────────────────────────────────────────

def _method_adjacency(files: List[FileAnalysisResult]) -> Dict[str, List[str]]:
    """method_name -> 內部被呼叫的 method_name 清單（鄰接表）。

    與 call_chain_builder._known_methods() 邏輯相同，這裡獨立一份小函式，避免
    為了共用一個私有函式而讓兩個模組互相耦合。
    """
    names: Set[str] = set()
    for fr in files:
        for cls in fr.classes:
            for m in cls.methods:
                names.add(m.name)

    adj: Dict[str, List[str]] = {}
    for fr in files:
        for cls in fr.classes:
            for m in cls.methods:
                targets = adj.setdefault(m.name, [])
                for call in m.calls:
                    if call in names and call != m.name and call not in targets:
                        targets.append(call)
    return adj


def _reachable_from(start: str, adj: Dict[str, List[str]], max_depth: int = 8) -> Tuple[List[str], Set[str]]:
    """從 start 出發，回傳 (一條代表性路徑, 所有可達的方法名稱集合)。

    代表性路徑只取第一個分支（僅供顯示用）；可達集合才是後續比對 SP/資料表
    關聯的實際依據，不會因為只取一條路徑而漏掉其他分支呼叫到的 SP。
    """
    visited: Set[str] = {start}
    path: List[str] = [start]

    node = start
    depth = 0
    while depth < max_depth:
        children = [c for c in adj.get(node, []) if c not in visited]
        if not children:
            break
        node = children[0]
        path.append(node)
        visited.add(node)
        depth += 1

    frontier = list(visited)
    while frontier:
        nxt: List[str] = []
        for n in frontier:
            for c in adj.get(n, []):
                if c not in visited:
                    visited.add(c)
                    nxt.append(c)
        frontier = nxt

    return path, visited


def _expand_sp_chain(
    root_sp_name: str,
    database_alias: Optional[str],
    db_server: Optional[str],
    db_name: Optional[str],
    max_depth: int,
    max_def_chars: int = 8000,
) -> List[dict]:
    """從一支 SP 出發，遞迴展開巢狀 EXEC 呼叫，回傳扁平清單（每筆含 called_by/depth，
    與這個專案既有的 related_programs 扁平加 depth 慣例一致）。每筆內容：
      - name：SP 名稱
      - exists：資料庫/快取中是否真的找得到這支 SP 的定義
      - tables：這支 SP 自己引用的資料表（純字串分析，見 extract_tables_from_definition）
      - called_by：呼叫它的上一層 SP 名稱（root 本身為空字串）
      - depth：巢狀層數（root 為 0）

    找不到定義（快取沒有、也連不到即時 DB）的 SP 仍會出現一筆，tables 為空、
    exists=False，讓呼叫端知道「這條鏈斷在這裡」，不是完全沒有這支 SP。
    """
    max_depth = min(max_depth, _MAX_SP_DEPTH_HARD_CAP)
    result: List[dict] = []
    if not root_sp_name:
        return result

    visited: Set[str] = set()
    queue: List[Tuple[str, str, int]] = [(root_sp_name, "", 0)]

    while queue:
        name, called_by, depth = queue.pop(0)
        key = _normalize_name(name)
        if not key or key in visited:
            continue
        visited.add(key)

        defs = fetch_sp_definitions(
            [name],
            database_alias=database_alias,
            db_server=db_server,
            db_name=db_name,
        )
        info = defs[0] if defs else {"name": name, "exists": False, "definition": "", "tables": []}
        definition = info.get("definition", "") or ""
        tables = info.get("tables", []) or (
            sorted(extract_tables_from_definition(definition)) if definition else []
        )

        result.append({
            "name": name,
            "exists": bool(info.get("exists", False)),
            "tables": tables,
            "called_by": called_by,
            "depth": depth,
        })

        if depth >= max_depth or not definition:
            continue

        nested = fetch_called_sp_names(definition, database_alias=database_alias, exclude_name=name)
        for nested_name in nested:
            if _normalize_name(nested_name) not in visited:
                queue.append((nested_name, name, depth + 1))

    return result


def build_forward_chain(
    matched_files: List[FileAnalysisResult],
    sp_relations: List,
    root: Path,
    anchor_method: str,
    database_alias: Optional[str] = None,
    db_server: Optional[str] = None,
    db_name: Optional[str] = None,
    max_sp_depth: int = 2,
    fk_depth: int = 1,
) -> Optional[dict]:
    """從指定的錨點方法出發，組出一條正向鏈。

    anchor_method：通常由 spec-rag 端依使用者問題的 UI 動作描述，用語意檢索從
    ui_fields 的 events 挑出的候選 handler 方法名稱（見這個模組頂部說明）；這裡
    只管照著這個名稱組鏈，不判斷這個名稱選得準不準。

    sp_relations：scan.sp_relations（List[CSharpSPRelation]，每筆帶
    csharp_file/method_name/sp_name），不是 FileAnalysisResult.stored_procedure_calls
    ——後者只有整份檔案層級的 SP 呼叫清單，沒有「是哪個方法呼叫的」這個關鍵資訊，
    沒辦法拿來對照 reachable_methods（哪些方法在這條呼叫鏈可達範圍內）。

    回傳 None 代表在 matched_files 裡完全找不到這個方法名稱（呼叫端應視為此
    錨點無效，換下一個候選）。
    """
    adj = _method_adjacency(matched_files)
    if anchor_method not in adj and not any(
        anchor_method == m.name for fr in matched_files for cls in fr.classes for m in cls.methods
    ):
        return None

    method_path, reachable_methods = _reachable_from(anchor_method, adj)

    # 直接呼叫的 SP：只比對「屬於這批 matched_files 的方法」呼叫到的 SP，避免
    # 跨程式同名方法造成誤判（例如另一支完全無關的程式也有一個叫 BindData 的方法）。
    # 比對用「檔名（不分大小寫）」而非完整路徑字串完全相等——scan.sp_relations
    # 裡的 csharp_file 與 csharp_results 裡的 file_path 即使指向同一個檔案，實務上
    # 仍可能有大小寫或路徑正規化的差異（這裡曾經因為用 exact set membership 導致
    # 明明存在的 SP 關聯完全比對不到，見 analyze_service.py 的 _file_matches()
    # 早就是用檔名比對而非完整路徑，這裡改成一致的做法）。
    file_names = {Path(fr.file_path).name.lower() for fr in matched_files}
    root_sps: List[Tuple[str, str]] = []  # (sp_name, called_by_method)
    seen_sp: Set[str] = set()
    for rel in sp_relations:
        if Path(rel.csharp_file).name.lower() not in file_names:
            continue
        if rel.method_name not in reachable_methods or not rel.sp_name:
            continue
        key = _normalize_name(rel.sp_name)
        if key not in seen_sp:
            seen_sp.add(key)
            root_sps.append((rel.sp_name, rel.method_name))

    sp_chain: List[dict] = []
    for sp_name, called_by_method in root_sps:
        expanded = _expand_sp_chain(sp_name, database_alias, db_server, db_name, max_sp_depth)
        for entry in expanded:
            if entry["depth"] == 0:
                entry["called_by_method"] = called_by_method
        sp_chain.extend(expanded)

    all_tables: Set[str] = set()
    for entry in sp_chain:
        all_tables.update(entry.get("tables", []))

    related_tables: List[str] = []
    if fk_depth > 0 and all_tables:
        related_tables = resolve_fk_related(
            sorted(all_tables),
            database_alias=database_alias,
            depth=fk_depth,
            db_server=db_server,
            db_name=db_name,
        )

    return {
        "anchor_method": anchor_method,
        "method_path": method_path,
        "reachable_methods": sorted(reachable_methods),
        "stored_procedures": sp_chain,
        "tables": sorted(all_tables),
        "related_tables_fk": related_tables,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 反向鏈：資料表（可選：欄位）-> SP -> C# 方法 -> UI 控制項事件
# ─────────────────────────────────────────────────────────────────────────────

def _table_referenced(definition: str, table_name: str) -> bool:
    tables = extract_tables_from_definition(definition)
    target = _normalize_name(table_name)
    return any(_normalize_name(t) == target for t in tables)


def _column_referenced(definition: str, column_name: str) -> bool:
    """欄位層級的近似比對：純文字搜尋，不解析 SQL 語法樹。

    這是刻意的設計取捨，不是偷懶：SP 的 SELECT/WHERE/SET 子句要精準解析出
    「這裡真的是在動這個欄位」成本很高、也容易因為 T-SQL 語法變化而出錯；
    改用「欄位名稱字串是否出現在 SP 定義文字裡」這種近似值，呼叫端（AI）在
    引用這個結果時應明確告知使用者這只是近似比對，不是保證。
    """
    import re
    if not column_name:
        return True
    pattern = re.compile(r"\b" + re.escape(column_name) + r"\b", re.IGNORECASE)
    return bool(pattern.search(definition))


def _find_ui_anchors_for_method(aspx_files: List[FileAnalysisResult], method_names: Set[str]) -> List[dict]:
    """在 aspx 解析結果的 ui_fields 裡，找出哪個控制項的 events 對應到這批方法名稱
    的任何一個（method_names 通常是「目標方法本身」加上「所有會（直接或間接）
    呼叫到它的方法」，見 _ancestors_of()——因為觸發 UI 事件的方法，往往不是真正
    存取資料表/呼叫 SP 的那個方法本身，而是它的上層呼叫者，例如
    btnDelete_Click（事件處理常式）呼叫 DeleteData（真正動資料庫的方法））。

    ui_fields 條目可能是巢狀結構（grid 的 fields、form_group 的 items 各自再有
    fields），需要遞迴走訪；grid 容器本身與獨立控制項都可能帶 events。
    """
    anchors: List[dict] = []

    def walk(entry: dict, file_path: str) -> None:
        events = entry.get("events") or {}
        for event_name, handler in events.items():
            if handler in method_names:
                anchors.append({
                    "file": file_path,
                    "control": entry.get("control", ""),
                    "id": entry.get("id", ""),
                    "event": event_name,
                    "handler": handler,
                })
        for sf in entry.get("fields", []) or []:
            walk(sf, file_path)
        for it in entry.get("items", []) or []:
            walk(it, file_path)

    for fr in aspx_files:
        for entry in fr.ui_fields or []:
            walk(entry, fr.file_path)

    return anchors


def _reverse_method_adjacency(files: List[FileAnalysisResult]) -> Dict[str, List[str]]:
    """method_name -> 呼叫它的 method_name 清單（跟 _method_adjacency 方向相反）。"""
    forward = _method_adjacency(files)
    rev: Dict[str, List[str]] = {}
    for caller, callees in forward.items():
        for callee in callees:
            rev.setdefault(callee, []).append(caller)
    return rev


def _ancestors_of(method_name: str, rev_adj: Dict[str, List[str]], max_depth: int = 8) -> Set[str]:
    """回傳所有（直接或間接）會呼叫到 method_name 的方法名稱（不含自己）。"""
    visited: Set[str] = {method_name}
    frontier = [method_name]
    depth = 0
    while frontier and depth < max_depth:
        nxt: List[str] = []
        for n in frontier:
            for caller in rev_adj.get(n, []):
                if caller not in visited:
                    visited.add(caller)
                    nxt.append(caller)
        frontier = nxt
        depth += 1
    visited.discard(method_name)
    return visited


def build_backward_chains(
    scan,
    root: Path,
    table_name: str,
    column_name: Optional[str] = None,
    database_alias: Optional[str] = None,
) -> List[dict]:
    """從指定的資料表（可選：欄位）出發，組出反向鏈候選清單。

    scan：ProjectScanResult（已合併好的整包掃描結果，含 csharp_results /
    aspx_results / sp_relations / table_relations）。

    每筆候選鏈：
      {
        "table": table_name, "column": column_name（如有指定）,
        "via": "direct_sql" | "stored_procedure",
        "sp_name": ...（via=stored_procedure 時才有）,
        "program": 檔名, "file": 相對路徑, "class": ..., "method": ...,
        "ui_anchors": [{"file", "control", "id", "event", "handler"}, ...],
      }

    ui_anchors 的反查不是只檢查「這個方法本身有沒有直接綁 UI 事件」——實務上
    真正動資料表的方法（如 DeleteData）常常不是事件處理常式本身，而是被事件
    處理常式（如 btnDelete_Click）呼叫。這裡用 scan.csharp_results 建一份反向
    呼叫關係（誰呼叫了誰），把「這個方法自己 + 所有會直接或間接呼叫到它的方法」
    一起拿去比對 UI 事件，才不會漏掉這種常見的多層呼叫情形。
    """
    chains: List[dict] = []
    seen: Set[Tuple[str, str]] = set()
    rev_adj = _reverse_method_adjacency(scan.csharp_results)

    def add_chain(csharp_file: str, class_name: str, method_name: str, via: str, sp_name: str = "") -> None:
        key = (csharp_file, method_name)
        if key in seen:
            return
        seen.add(key)
        candidate_methods = {method_name} | _ancestors_of(method_name, rev_adj)
        ui_anchors = _find_ui_anchors_for_method(scan.aspx_results, candidate_methods)
        entry = {
            "table": table_name,
            "via": via,
            "program": Path(csharp_file).name,
            "file": _rel(csharp_file, root),
            "class": class_name,
            "method": method_name,
            "ui_anchors": ui_anchors,
        }
        if column_name:
            entry["column"] = column_name
        if sp_name:
            entry["sp_name"] = sp_name
        chains.append(entry)

    # 1) 直接用 SQL 存取此表的 C# 方法（table_relations，不需要資料庫連線）
    table_norm = _normalize_name(table_name)
    for rel in scan.table_relations:
        if _normalize_name(rel.table_name) != table_norm:
            continue
        add_chain(rel.csharp_file, rel.class_name, rel.method_name, via="direct_sql")

    # 2) 透過 SP 引用此表（比對本機 SQL 快取的 SP 定義文字；欄位為近似比對）
    cached = load_cached(database_alias) if database_alias else None
    sp_hits: List[str] = []
    if cached:
        for proc in cached.get("procedures", []):
            definition = proc.get("definition", "") or ""
            if not definition or not _table_referenced(definition, table_name):
                continue
            if column_name and not _column_referenced(definition, column_name):
                continue
            sp_hits.append(proc.get("name", ""))

    if sp_hits:
        sp_hits_norm = {_normalize_name(n) for n in sp_hits}
        for rel in scan.sp_relations:
            if _normalize_name(rel.sp_name) in sp_hits_norm:
                add_chain(rel.csharp_file, rel.class_name, rel.method_name, via="stored_procedure", sp_name=rel.sp_name)

    return chains
