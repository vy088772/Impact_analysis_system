# service/scan_store.py
"""
靜態掃描結果的持久化快取。

第一次掃描某路徑後，將 ProjectScanResult 以 pickle 寫入 data/scan_cache，
之後直接載入，避免每次重新解析 C#（整個 TTPUR 約數百檔、需數分鐘）。
只有在 refresh=True（更新指令）時才重新掃描並覆寫快取。
"""
from __future__ import annotations

import hashlib
import json
import pickle
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

from config.settings import settings
from code_analyzer.project_scanner import ProjectScanner, ProjectScanResult

# 快取格式版本：模型結構若變動可遞增，使舊快取自動失效
# v2：csharp_parser.METHOD_PATTERN 修正「省略存取修飾詞（隱含 private）的方法
# 會被漏掉」的問題，方法清單內容改變，故遞增版本號讓舊快取失效、強制重新掃描。
# v3：csharp_parser._extract_method_calls 改為保留呼叫的限定子（如
# "CommonFunction.AlertMsg" 而非只有 "AlertMsg"），供 reference_expander
# 精準解析同名方法歸屬哪個類別；MethodInfo.calls 內容格式改變，故遞增版本號。
# v4：ProjectScanResult 新增 aspx_results/razor_results/vue_results 欄位
# （scan_project() 開始實際呼叫 ASPXParser/RazorParser/VueParser），舊快取的
# pickle 物件沒有這些屬性，存取時會 AttributeError，故遞增版本號使舊快取失效。
# v5：FileAnalysisResult 新增 ui_fields 欄位（ASPXParser 額外整理 GridView 欄位
# HeaderText、Label/Button Text 等「畫面實際顯示文字」），舊快取的 FileAnalysisResult
# 物件沒有此屬性，故遞增版本號使舊快取失效、強制重新掃描以補上。
# v6：ASPXParser._extract_ui_fields 改為依所屬 GridView/DataGrid 分組（含該 Grid 的
# OnRowCommand/OnRowDataBound 等事件）並補上 DataField，ui_fields 內容結構整個改變
# （舊版是扁平清單），故遞增版本號使舊快取失效。
# v7：修正 ASPXParser.CONTROL_PATTERN 在屬性值含 '>'（如 ASP.NET 資料繫結運算式
# CommandArgument='<%# Container.DataItemIndex %>'）時會提早截斷標籤、遺漏後續屬性
# （如 Text、CommandName）的問題；另新增 ui_fields 的 'form'（查詢區塊 <th> 標籤文字
# 與相鄰輸入控制項對應）與 'script'（純前端 <script> 區塊原始碼）兩種項目，故遞增
# 版本號使舊快取失效、強制重新掃描以補上正確結果。
# v8：修正 ASPXParser._parse_attributes 用共用字元類別 [^"\']（同時排除雙引號與
# 單引號）比對屬性值，導致單引號屬性值裡若含雙引號（ASP.NET 資料繫結運算式很常見，
# 例如 Text='<%# Eval("IVNO") %>'）會被提早截斷，遺漏該屬性後半段與後續屬性
# （影響範圍不只 HyperLink，任何混用引號的屬性值都會中獎）；另新增 'hyperlink'
# 至 _DISPLAY_TEXT_CONTROLS（先前完全未擷取 asp:HyperLink 的 Text），並新增
# navigate_to（從 NavigateUrl 擷取目標頁面檔名）欄位，故遞增版本號使舊快取失效。
# v9：ASPXParser._extract_form_fields 改為把同一個 <table>/<div> 容器內的多個
# <th> 欄位（例如新增視窗的完整表單）合併成單一 kind="form_group" 區塊（原本每個
# <th> 各自一個 kind="form" 項目，容易被下游語意檢索只挑中其中一兩個、漏掉同一張
# 表單的其他欄位），並新增 _extract_js_id_bindings() 偵測 $("[id$=控制項ID]") 形式
# 的前端 JS 綁定（如自動完成函式），附加在對應欄位的 js_binding 屬性上——這些都是
# ui_fields 內容結構的變更，故遞增版本號使舊快取失效。
# v10：ASPXParser._extract_form_fields 新增 css_class（控制項 CssClass 屬性，如
# "StringFormat RequireColumn"——這類專案常見的宣告式前端驗證慣例，必填/格式規則
# 掛在 class 名稱上、由共用 script 依 hasClass() 判斷）與 max_length（MaxLength
# 屬性，瀏覽器端長度上限）兩個欄位。先前這兩者完全沒有擷取，導致「必填/長度限制
# 明明存在於 markup，卻只實作在前端、後端 CheckXxxData() 看不到」的規則會被誤判
# 成「沒有這條規則」。故遞增版本號使舊快取失效。
# v11：ASPXParser._extract_ui_fields 的獨立控制項（不在 GridView/DataGrid 內，
# 例如頁面上單獨一個按鈕）entry 新增 events 欄位（複製自 control.events，如
# {"OnClick": "btnDelete_Click"}）。先前只有 Grid 容器層級事件（OnRowCommand 等）
# 有寫進 ui_fields，獨立控制項的事件完全沒有，導致「按下這個按鈕會呼叫哪個方法」
# 這種畫面動作到後端方法的對應，對獨立按鈕完全找不到。故遞增版本號使舊快取失效。
# v12：ProjectScanner._find_class_and_method 修正一個長期存在的錯誤歸屬 bug——
# 舊邏輯「遇到第一個起始行號 <= 呼叫行號的方法就回傳」，由於 cls.methods 依宣告
# 順序排列，類別中最早宣告的方法（WebForms 常見的 Page_Load）幾乎必然滿足這個
# 條件，導致同一支程式裡「所有」SP／資料表呼叫，不論實際寫在哪個方法裡，全部被
# 誤判成 Page_Load 呼叫的。修正為「取起始行號 <= 呼叫行號中最大者」（該行之前最後
# 宣告的方法），使 sp_relations／table_relations 的 method_name 欄位變得可信。
# 此為既有欄位「內容」的修正（不是新增欄位），但影響既有 method_name 的實際值，
# 故仍遞增版本號使舊快取失效，讓使用者重新掃描後拿到正確歸屬。
# v14：CSharpParser._find_nearest_variable_assignment 修正一個錯誤排序 bug——
# 「宣告 → 條件式重新賦值 → 呼叫」這種常見寫法（例如依下拉選單值切換要呼叫的
# SP：`string sql = "spA"; if (...) { sql = "spB"; } obj.CreateTable(sql, ...);`），
# 舊邏輯把「只比對宣告」的 matches2 直接接在「宣告+重新賦值都比對得到」的
# matches1 後面（`matches1 + matches2`），取 `[-1]` 並不是「文字位置最後一筆」，
# 而是「串接後清單最後一筆」——matches2 只會命中最前面的宣告，串接後反而排在
# matches1 找到的重新賦值後面，導致誤取到「最前面的宣告」（如 spSelMasterQryV2）
# 而非「最接近呼叫點的重新賦值」（如 spSelMasterQryV3），使條件分支實際呼叫的 SP
# 完全消失在 sp_relations 裡。修正為依 match.start() 排序後再取最後一筆。此為既有
# 欄位「內容」的修正，影響任何「同一變數先宣告、後續依條件重新賦值再呼叫」寫法
# 的程式所抓到的 SP 名稱，故遞增版本號使舊快取失效。
# v15：ProjectScanResult 新增最新 C# 完整 source snapshot（content hash + 內容），
# 供後續 Execution Path 依 source span 精確取回原始碼，舊 pickle 沒有這份證據。
# v16：ProjectScanResult 新增 StaticAnalyzerHost 的 raw db_invocations 與每檔案
# connection_sources，供 Execution Path 在 /analyze 時直接接上 SQL graph；舊快取
# 沒有這些欄位，必須重新掃描。
# v17：StaticAnalyzerHost raw db_invocations 新增 branch_context 與 Dapper/Entity
# Framework adapter facts；舊快取沒有這些新證據，必須重新掃描。
# v18：legacy regex SP relations moved to legacy_sp_relations; formal consumers use
# raw db_invocations plus CSharpAnalysisGateway.
# v19：legacy_sp_relations are transient comparison input and are excluded from
# ProjectScanResult serialization; cached scans must not retain a second relation source.
# v20：remove legacy SP-based database inference from formal table facts.
# v21：external wrapper raw facts include receiver type metadata.
# v22：unknown external wrapper mode inference no longer treats a boolean argument
# on calls whose first argument is not command-text-shaped as stored-procedure mode.
_CACHE_VERSION = 24

# 同 process 內的記憶體快取（避免重複反序列化）
_mem_cache: Dict[str, ProjectScanResult] = {}


def _cache_root() -> Path:
    root = Path(settings.SCAN_CACHE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _key(root: Path) -> str:
    return hashlib.sha1(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


def _paths(root: Path) -> tuple[Path, Path]:
    k = _key(root)
    return _cache_root() / f"{k}.pkl", _cache_root() / f"{k}.meta.json"


def has_cache(root: Path) -> bool:
    return _load(root) is not None


def load_cached(root: Path) -> Optional[ProjectScanResult]:
    """Load a current scan cache without ever starting a new scan."""
    key = str(root.resolve())
    if key in _mem_cache:
        return _mem_cache[key]
    cached = _load(root)
    if cached is not None:
        _mem_cache[key] = cached
    return cached


def cache_status(root: Path) -> str:
    """Return whether a scan cache is current, stale, missing, or invalid."""
    pkl, meta = _paths(root)
    if not pkl.exists() or not meta.exists():
        return "missing"
    try:
        info = json.loads(meta.read_text(encoding="utf-8"))
    except Exception:
        return "invalid"
    if info.get("cache_version") != _CACHE_VERSION:
        return "stale"
    return "current" if _load(root) is not None else "invalid"


def _git_head_commit(path: Path) -> Optional[str]:
    """從 path 往上尋找 .git 目錄，讀取目前 HEAD 的 commit hash。

    只讀取本機已 clone 的 repo 現況（`git rev-parse HEAD`），不連網路、不觸發
    任何 fetch/pull。找不到 .git（例如尚未 clone）或指令失敗時回傳 None。
    """
    cur = path.resolve()
    for _ in range(6):  # 最多往上找 6 層，避免子路徑巢狀過深時無止盡往上尋找
        if (cur / ".git").exists():
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(cur),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    return result.stdout.strip()
            except Exception:
                pass
            return None
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def cached_commit(root: Path) -> Optional[str]:
    """讀取快取寫入當下記錄的原始碼 commit hash（僅供狀態檢查用途，不驗證
    cache_version，純粹反映『上次掃描時 repo 是哪個 commit』）。
    """
    _, meta = _paths(root)
    if not meta.exists():
        return None
    try:
        info = json.loads(meta.read_text(encoding="utf-8"))
        return info.get("source_commit")
    except Exception:
        return None


def current_commit(root: Path) -> Optional[str]:
    """讀取 root 所屬 git repo『目前』本機的 HEAD commit hash（不連網路、不觸發
    pull），用於跟 cached_commit() 比對是否有新 commit 尚未重新掃描。
    """
    return _git_head_commit(root)


def _load(root: Path) -> Optional[ProjectScanResult]:
    pkl, meta = _paths(root)
    if not pkl.exists():
        return None
    try:
        if meta.exists():
            info = json.loads(meta.read_text(encoding="utf-8"))
            if info.get("cache_version") != _CACHE_VERSION:
                return None
        with pkl.open("rb") as f:
            return pickle.load(f)
    except Exception:
        # 反序列化失敗（模型變動等）→ 視為無快取
        return None


def _save(root: Path, result: ProjectScanResult) -> None:
    pkl, meta = _paths(root)
    try:
        with pkl.open("wb") as f:
            pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
        meta.write_text(
            json.dumps(
                {
                    "cache_version": _CACHE_VERSION,
                    "root": str(root.resolve()),
                    "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "source_commit": _git_head_commit(root),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # 寫檔失敗不致命
        print(f"⚠️  掃描快取寫出失敗（非致命）：{exc}")


def save_scan(root: Path, result: ProjectScanResult) -> None:
    """Persist an already-mutated scan result and update the process cache."""
    _mem_cache[str(root.resolve())] = result
    _save(root, result)


def get_or_scan(root: Path, refresh: bool = False) -> ProjectScanResult:
    """
    取得掃描結果：優先用記憶體 / 磁碟快取；refresh=True 則強制重新掃描。
    """
    key = str(root.resolve())

    if not refresh:
        if key in _mem_cache:
            return _mem_cache[key]
        cached = _load(root)
        if cached is not None:
            _mem_cache[key] = cached
            print(f"⚡ 使用快取掃描結果：{root}")
            return cached

    print(f"🔍 重新掃描程式碼：{root}")
    scanner = ProjectScanner(project_root=str(root))
    result = scanner.scan_project(analyze_sp=False)
    _mem_cache[key] = result
    _save(root, result)
    return result


def clear_cache(root: Path) -> None:
    """清除指定路徑的磁碟與記憶體快取。"""
    pkl, meta = _paths(root)
    for p in (pkl, meta):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    _mem_cache.pop(str(root.resolve()), None)
