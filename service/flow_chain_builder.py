# service/flow_chain_builder.py
"""
變更影響「關係鏈」建構（無 AI）。

把既有的靜態分析關聯（方法呼叫鏈、C#到SP關聯、C#到資料表關聯、View 層控制項
事件、SP 內部巢狀呼叫、SP 引用資料表）串成結構化的候選鏈，交給
呼叫端（spec-rag 的 mode 3 agent）自行判斷哪一條鏈才是使用者實際要問的那個——
這裡只負責把鏈算出來，不做任何「這條鏈跟問題相不相關」的判斷。

兩種方向：
  - forward（build_forward_chain）：從指定的錨點方法（通常是 spec-rag 端依
    UI 動作用語意檢索，從 ui_fields 的 events 挑出的候選 handler 方法名稱）出發，
    沿每個呼叫的 Bound Call Target（ADR-0044）走進掃描根目錄裡的任何檔案（例如
    controller action 呼叫的 service 方法），再依 SQL Execution Graph 的 sp_chain 列出 SP（含巢狀呼叫），
    最後彙整這些 SP 引用的資料表；同時也會補上可達方法的 inline SQL table
    relation（C# Scan Result 的 table_relations，經 inline table relations
    module 的 by-method query 取得）所列的資料表（`inline_sql_tables`），涵蓋
    完全沒呼叫 SP、只靠內嵌 SQL 查表的方法（例如只是組 DropDownList 選項的
    BindXxx 方法）。
  - backward（build_backward_chains）：從指定的資料表（可選：欄位名稱）出發，
    反查哪些 SP 引用了這張表，再反查哪些 C# 方法呼叫了這些 SP（或直接用 SQL
    存取這張表，經 inline table relations module 的 by-table query 取得），
    最後反查哪個 UI 控制項事件會觸發這個方法。

兩個方向讀同一份 table_relations，所以同一個方法在兩個方向列出同一批 inline
SQL 資料表。

已知限制（誠實標注，不假裝是保證）：
  - 欄位（column）層級的比對是「SQL Execution Graph 路徑中繼資料（written_columns、
    conditions、reads、writes）裡有沒有出現這個欄位名稱字串」的近似值（文字比對），
    不是解析 SQL 語法樹後的結構化保證，可能有誤判（欄位名稱剛好也是變數名或
    其他表的欄位名）。
  - UI 控制項事件反查是用「同目錄同檔名，.aspx.cs 對應 .aspx」的 WebForms
    命名慣例配對 code-behind 與 aspx 檔案，非 WebForms 專案（無對應 .aspx）
    這段會自然找不到、留空，不影響其餘鏈的建構。
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple

from canonical_object_identity import bare_key
from code_analyzer.csharp_analysis_gateway import DbInvocation, WRAPPER_EVIDENCE_FIELDS
from code_analyzer.models import CallSite, FileAnalysisResult
from code_analyzer.project_scanner import ProjectScanResult
from . import inline_table_relations
from .call_graph_nodes import MethodNodes
from .graph_queries import filter_table_accesses, query_table_accesses
from .program_screen import ProgramScreen
from .sql_cache_store import CacheIdentity
from .table_match import TableQuestion
from .execution_path_builder import build_execution_paths


def _rel(file_path: str, root: Path) -> str:
    try:
        return str(Path(file_path).resolve().relative_to(root.resolve()))
    except Exception:
        return file_path


def _wrapper_projection_fields(source: Mapping[str, object]) -> dict[str, object]:
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key in (*WRAPPER_EVIDENCE_FIELDS, "unresolved_reason")
        if key in source
        for value in (source[key],)
    }


# ─────────────────────────────────────────────────────────────────────────────
# 正向鏈：錨點方法 -> 呼叫鏈 -> SP -> SP -> 資料表
# ─────────────────────────────────────────────────────────────────────────────

def _method_adjacency(files: List[FileAnalysisResult]) -> Dict[str, List[str]]:
    """method_name -> 內部被呼叫的 method_name 清單（鄰接表）。

    只剩反向鏈用它（以呼叫文字比對方法名稱）；正向鏈改用 Bound Call Target，見
    _bound_call_graph。
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


class _CallGraph(NamedTuple):
    """The call graph of a scan, from the Bound Call Targets of its calls (ADR-0044)."""

    # node -> the nodes that its calls reach.
    edges: Dict[str, List[str]]
    # node -> one diagnostic for each of its calls that has no Bound Call Target.
    unresolved_calls: Dict[str, List[dict]]
    # node -> the bare method name, for the outputs that name a method.
    method_names: Dict[str, str]


def _bound_call_graph(scan: ProjectScanResult) -> _CallGraph:
    """The call graph of the whole scan root.

    A node is one bound method symbol (`MethodSourceSpan.node`), so two overloads, and two
    methods with the same name in two classes, stay two nodes. The edges come from every source file of the scan
    root, not from the program files only: an action reaches the service methods that it
    calls. A call with no Bound Call Target gives no edge, and the call text is never
    matched by name. Such a call stays in `unresolved_calls`, so the chain can say why its
    branch stops (ticket 06).
    """
    edges: Dict[str, List[str]] = {}
    unresolved: Dict[str, List[dict]] = {}
    method_names: Dict[str, str] = {}
    for key, snapshot in getattr(scan, "source_snapshots", {}).items():
        relative_path = str(snapshot.relative_path or key).replace("\\", "/")
        for span in snapshot.method_spans:
            if not span.node:
                continue
            method_names[span.node] = span.method_name
            targets = edges.setdefault(span.node, [])
            for call in span.calls:
                target = call.bound_target
                if target:
                    method_names.setdefault(target, call.target_method)
                    if target != span.node and target not in targets:
                        targets.append(target)
                elif call.unresolved_reason:
                    unresolved.setdefault(span.node, []).append(
                        _unresolved_call_diagnostic(
                            f"{span.class_name}.{span.method_name}", call, relative_path
                        )
                    )
    return _CallGraph(edges, unresolved, method_names)


def bound_call_edges(scan: ProjectScanResult) -> Dict[str, List[str]]:
    """node -> the nodes that its calls reach, from the Bound Call Targets of the scan.

    This is the one rule for which method a call reaches (ADR-0044). The flow chain and
    the related program expansion of `/analyze` both use it. The expansion lists files,
    not reasons, so it leaves out `unresolved_calls`: a call with no target lists nothing.
    """
    return _bound_call_graph(scan).edges


def _unresolved_call_diagnostic(caller: str, call: CallSite, relative_path: str) -> dict:
    """The `diagnostics` entry of a call with no Bound Call Target: the caller, the call, the reason.

    `caller` is `Class.Method`, the simple names; `source_span` tells the overload apart.

    `reason` and `unresolved_reason` both hold the reason, the two names an unproven
    execution path in the same list carries.
    """
    return {
        "kind": "unresolved_call",
        "caller": caller,
        "call": call.call_text,
        "reason": call.unresolved_reason,
        "unresolved_reason": call.unresolved_reason,
        "candidate_classes": list(call.candidate_classes),
        "source_span": {
            "relative_path": relative_path,
            "start_offset": call.start_offset,
            "end_offset": call.end_offset,
        },
    }


def _inline_sql_tables(
    scan: ProjectScanResult, nodes: MethodNodes, reachable_nodes: Set[str]
) -> Set[str]:
    """列出可達方法的 inline SQL table relation 所指的資料表名稱，補足 SP 鏈以外的來源。

    有些方法（例如只組 DropDownList 選項的 BindXxx）直接用
    `obj.CreateReader("select ... from Table")` 這種內嵌 SQL 字串查資料，完全
    沒有 database invocation，這種情況下只看 SQL Execution Graph path 也不會涵蓋它。
    掃描時已經把這些 SQL 轉成 table relation；這裡只挑出「可達節點」的那些
    relation。relation 以它所在的行找到包住它的方法 span，用那個 span 的節點比對
    （ADR-0044），不用它記錄的類別與方法名稱，所以同名的 overload 不會互相沾到。
    """
    return set(
        inline_table_relations.table_names_by_method(
            scan,
            lambda site: nodes.at_line(site.file_path, site.line_number) in reachable_nodes,
        )
    )


class ForwardReach(NamedTuple):
    """The methods that an anchor action reaches through its Bound Call Targets."""

    # 一條代表性路徑（僅供顯示用），每一段是一個節點（`MethodSourceSpan.node`）。
    node_path: List[str]
    # 所有可達的節點；SP 與資料表關聯以它為依據。
    nodes: Set[str]
    # 可達節點裡沒有 Bound Call Target 的呼叫（diagnostics 條目）；那些分支停在這裡。
    unresolved_calls: List[dict]
    # 節點 -> 方法名稱（不含類別與參數），給回應裡列方法名稱的欄位用。
    names: Mapping[str, str]

    @property
    def method_path(self) -> List[str]:
        """The representative path as bare method names, the shape `/flow_chain` answers."""
        return [self.names[node] for node in self.node_path]

    @property
    def method_names(self) -> Set[str]:
        """The reached methods as bare names, the shape `reachable_methods` answers."""
        return {self.names[node] for node in self.nodes}


def _reachable_from(starts: List[str], adj: Dict[str, List[str]]) -> Tuple[List[str], Set[str]]:
    """從 starts 出發，回傳 (一條代表性路徑, 所有可達的節點集合)。

    代表性路徑只取第一個分支（僅供顯示用）；可達集合才是後續比對 SP/資料表
    關聯的實際依據，不會因為只取一條路徑而漏掉其他分支呼叫到的 SP。兩者都沒有
    深度上限，visited 集合擋下每一個循環（ADR-0044）。
    """
    visited: Set[str] = set(starts)
    path: List[str] = starts[:1]

    node = path[0] if path else ""
    while node:
        children = [c for c in adj.get(node, []) if c not in visited]
        node = children[0] if children else ""
        if node:
            path.append(node)
            visited.add(node)

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


def forward_reach(
    scan: ProjectScanResult,
    anchor_method: str,
    *,
    owns_file: Callable[[str], bool],
    owns_action: Callable[[str, str], bool],
) -> Optional[ForwardReach]:
    """The nodes that `anchor_method` reaches, or None when the program owns no such action.

    The program scope (ADR-0019) selects the anchor action only. The anchor is a name, so
    each overload of that name starts the reach: a GET and a POST action of one name both
    start. From the anchor, the reach follows each Bound Call Target into any file of the
    scan root.
    """
    method_nodes = MethodNodes(scan)
    starts = sorted(
        {
            span.node
            for fr in scan.csharp_results
            if owns_file(fr.file_path)
            for span in method_nodes.spans_of(fr.file_path)
            if span.method_name == anchor_method and owns_action(fr.file_path, span.method_name)
        }
    )
    if not starts:
        return None
    graph = _bound_call_graph(scan)
    node_path, nodes = _reachable_from(starts, graph.edges)
    unresolved_calls = [
        diagnostic for node in sorted(nodes) for diagnostic in graph.unresolved_calls.get(node, [])
    ]
    return ForwardReach(node_path, nodes, unresolved_calls, graph.method_names)


def _caller_names(path: Mapping[str, object]) -> Optional[Tuple[str, str]]:
    """The class and the name of the method that holds a path's Database Invocation, or None.

    A path that names the method but no class takes the class of its entry method. The
    backward chain shows these names; the node comes from `_caller_node`.
    """
    caller_method = str(path.get("caller_method") or "")
    if not caller_method:
        return None
    caller_class = str(path.get("caller_class") or "")
    if not caller_class:
        caller_class = str(path.get("entry_method") or "").rpartition(".")[0]
    return caller_class, caller_method


def _caller_node(nodes: MethodNodes, path: Mapping[str, object]) -> str:
    """The node of the method that holds a path's Database Invocation, or "" when unknown.

    The method span that holds the source span of the path gives the node (ADR-0044); its
    class name and method name do not, so an overload never takes the path of another.
    The chain joins a path by this node, not by `entry_method`: the entry method is the
    outermost caller of a same-file chain that the call text gives, and the call graph
    already reaches every caller through its Bound Call Targets.
    """
    return nodes.of_source_span(path.get("source_span"))


def files_of_nodes(scan: ProjectScanResult, nodes: Set[str]) -> List[FileAnalysisResult]:
    """The C# file results that declare at least one of `nodes`, in scan order."""
    method_nodes = MethodNodes(scan)
    return [
        fr
        for fr in scan.csharp_results
        if any(span.node in nodes for span in method_nodes.spans_of(fr.file_path))
    ]


def build_forward_chain(
    scan: ProjectScanResult,
    anchor_method: str,
    *,
    owns_file: Callable[[str], bool],
    owns_action: Callable[[str, str], bool] = lambda file_path, method_name: True,
    graph: Optional[Mapping[str, object]] = None,
    invocations: Iterable[DbInvocation] = (),
    execution_paths: Optional[List[dict]] = None,
    reach: Optional[ForwardReach] = None,
) -> Optional[dict]:
    """從指定的錨點方法出發，組出一條正向鏈。

    anchor_method：通常由 spec-rag 端依使用者問題的 UI 動作描述，用語意檢索從
    ui_fields 的 events 挑出的候選 handler 方法名稱（見這個模組頂部說明）；這裡
    只管照著這個名稱組鏈，不判斷這個名稱選得準不準。

    scan：ProjectScanResult，inline SQL 資料表取自它的 table_relations，呼叫圖取自
    它的 source_snapshots 裡每個方法的 Bound Call Target。
    owns_file：一個檔案路徑是否屬於這支程式；錨點只在通過它的檔案裡找。
    owns_action：這支程式是否擁有某檔案裡的某個 action；錨點必須是這支程式擁有的
    action（WebForms 程式擁有檔案內所有方法）。錨點之後的呼叫不受這兩個條件限制。
    execution path 以它所在的方法（`caller_class.caller_method`）比對可達節點。
    reach：呼叫端已經用 forward_reach 算好的可達節點；沒有時這裡自己算。

    回傳 None 代表在這支程式的檔案裡完全找不到這個方法名稱，或它不是這支程式
    擁有的 action（呼叫端應視為此錨點無效，換下一個候選）。
    """
    if reach is None:
        reach = forward_reach(scan, anchor_method, owns_file=owns_file, owns_action=owns_action)
    if reach is None:
        return None
    method_path, reachable_nodes = reach.method_path, reach.nodes
    method_nodes = MethodNodes(scan)

    # Gateway + graph paths are the formal source for database calls.
    supplied_paths = execution_paths
    execution_paths = []
    if graph:
        execution_paths = [
            path
            for path in (
                supplied_paths
                if supplied_paths is not None
                else build_execution_paths(invocations, graph)
            )
            if not _caller_node(method_nodes, path) or _caller_node(method_nodes, path) in reachable_nodes
        ]

    formal_sp_chain: List[dict] = []
    all_tables: Set[str] = set()
    unresolved_paths: List[dict] = []
    if graph:
        graph_nodes = {
            str(node.get("id")): node
            for node in graph.get("nodes", []) or []
            if node.get("id")
        }
        for path in execution_paths:
            path_tables = set(path.get("reads", []) or []) | set(path.get("writes", []) or [])
            if path.get("evidence") != "proven":
                unresolved_paths.append(path)
                continue
            all_tables.update(path_tables)
            sp_chain = list(path.get("sp_chain", []) or [])
            for depth, name in enumerate(sp_chain):
                module_node = next(
                    (
                        node
                        for node in graph_nodes.values()
                        if node.get("type") == "stored_procedure"
                        and bare_key(node.get("name")) == bare_key(name)
                    ),
                    None,
                )
                formal_sp_chain.append(
                    {
                        "name": name,
                        "exists": module_node is not None,
                        "tables": sorted(path_tables),
                        "called_by": sp_chain[depth - 1] if depth else "",
                        "depth": depth,
                        "evidence": path.get("evidence", "unresolved"),
                        "path_id": path.get("path_id", ""),
                        "conditions": list(path.get("conditions", []) or []),
                    }
                )
                formal_sp_chain[-1].update(_wrapper_projection_fields(path))

    sp_chain = formal_sp_chain

    # 補上可達方法的 inline SQL table relation 所列的資料表（見 _inline_sql_tables 說明）——
    # 有些方法完全沒呼叫 SP，只靠內嵌 SQL 字串查表，單看 sp_chain 會漏掉這些表。
    # 獨立回傳一份（inline_sql_tables）方便呼叫端知道「這些表不是從哪支 SP 來的」，
    # 同時也併入 all_tables，讓 tables/FK 展開跟 SP 來源的表一視同仁。
    inline_tables = _inline_sql_tables(scan, method_nodes, reachable_nodes)
    all_tables.update(inline_tables)

    return {
        "anchor_method": anchor_method,
        "method_path": method_path,
        "reachable_methods": sorted(reach.method_names),
        "stored_procedures": sp_chain,
        "execution_paths": execution_paths,
        "diagnostics": [
            *(path for path in execution_paths if path.get("evidence") != "proven"),
            *reach.unresolved_calls,
        ],
        "unresolved_paths": unresolved_paths,
        "tables": sorted(all_tables),
        "inline_sql_tables": sorted(inline_tables),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 反向鏈：資料表（可選：欄位）-> SP -> C# 方法 -> UI 控制項事件
# ─────────────────────────────────────────────────────────────────────────────

def _paired_view_file_names(csharp_file: str) -> Set[str]:
    """WebForms 命名慣例：`Foo.aspx.cs`/`Foo.ascx.cs` 的畫面檔案是同目錄的
    `Foo.aspx`/`Foo.ascx`。回傳期望的畫面檔名（不含目錄，小寫），非
    `.aspx.cs`/`.ascx.cs` 命名（例如共用的 helper 類別、Web API controller）則
    回傳空集合——呼叫端遇到空集合應視為「這個方法本身沒有對應畫面」，而不是
    退回去比對整個 repo（那正是這裡要修的過度比對問題）。
    """
    name = Path(csharp_file).name.lower()
    for suffix in (".aspx.cs", ".ascx.cs"):
        if name.endswith(suffix):
            return {name[: -len(".cs")]}
    return set()


def _find_ui_anchors_for_method(
    aspx_files: List[FileAnalysisResult],
    method_names: Set[str],
    csharp_file: str,
) -> List[dict]:
    """在 aspx 解析結果的 ui_fields 裡，找出哪個控制項的 events 對應到這批方法名稱
    的任何一個（method_names 通常是「目標方法本身」加上「所有會（直接或間接）
    呼叫到它的方法」，見 _ancestors_of()——因為觸發 UI 事件的方法，往往不是真正
    存取資料表/呼叫 SP 的那個方法本身，而是它的上層呼叫者，例如
    btnDelete_Click（事件處理常式）呼叫 DeleteData（真正動資料庫的方法））。

    只在「這個方法所屬的 csharp_file 依 WebForms 命名慣例對應到的那個畫面檔案」
    裡找，不會掃整個 repo 的 aspx_results——ASP.NET WebForms 專案裡
    `btnQry_Click`/`btnSend_Click`/`gvData_PageIndexChanging` 這類事件處理常式
    名稱是極常見的樣板命名，幾十個完全無關的畫面都可能剛好用同一個 handler
    名稱；先前沒有這層限制時，比對會把這些完全無關頁面的按鈕全部誤判成這個
    方法的觸發來源，讓 ui_anchors 塞滿看起來毫無關聯的項目。

    ui_fields 條目可能是巢狀結構（grid 的 fields、form_group 的 items 各自再有
    fields），需要遞迴走訪；grid 容器本身與獨立控制項都可能帶 events。
    """
    anchors: List[dict] = []
    paired_names = _paired_view_file_names(csharp_file)
    if not paired_names:
        return anchors

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
        if Path(fr.file_path).name.lower() not in paired_names:
            continue
        for entry in fr.ui_fields or []:
            walk(entry, fr.file_path)

    return anchors


def _reverse_edges(edges: Mapping[str, List[str]]) -> Dict[str, List[str]]:
    """node -> the nodes that call it: the Bound Call Target edges in reverse (ADR-0044)."""
    callers: Dict[str, List[str]] = {}
    for caller, callees in edges.items():
        for callee in callees:
            callers.setdefault(callee, []).append(caller)
    return callers


def _screen_anchors_by_node(
    scan: ProjectScanResult, root: Path, screens: Sequence[ProgramScreen]
) -> Dict[str, List[dict]]:
    """node of an action -> one `ui_anchors` entry for each Program Screen that holds it.

    The strength is the strength of the screen-to-action link (ADR-0019): `determined`
    for a same-name action or a markup-layer View Anchor, `likely` for a script URL.
    An action is a name, so each overload of that name is a node of the action.
    """
    method_nodes = MethodNodes(scan)
    anchors: Dict[str, List[dict]] = {}
    for screen in screens:
        for action in screen.actions:
            for node in sorted(
                {
                    span.node
                    for span in method_nodes.spans_of(action.controller_path)
                    if span.method_name == action.name
                }
            ):
                anchors.setdefault(node, []).append(
                    {
                        "kind": "program_screen",
                        "file": _rel(screen.view_path, root),
                        "view": screen.view_name,
                        "controller_file": _rel(action.controller_path, root),
                        "action": action.name,
                        "strength": action.strength,
                    }
                )
    return anchors


def _reverse_method_adjacency(files: List[FileAnalysisResult]) -> Dict[str, List[str]]:
    """method_name -> 呼叫它的 method_name 清單（跟 _method_adjacency 方向相反）。"""
    return _reverse_edges(_method_adjacency(files))


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
    graph: Optional[Mapping[str, object]] = None,
    invocations: Iterable[DbInvocation] = (),
    database: str = "",
    *,
    sql_cache_identity: Optional[CacheIdentity],
    execution_paths: Optional[Iterable[Mapping[str, object]]] = None,
    program_screens: Sequence[ProgramScreen] = (),
) -> List[dict]:
    """從指定的資料表（可選：欄位）出發，組出反向鏈候選清單。

    database：請求的 Database；資料表名稱沒寫 database 時取這個值，比對規則見 table_match。
    sql_cache_identity：handler 建好的 SQL 快取身分（沒有時為 None）；inline SQL 補 schema 時用它。

    scan：ProjectScanResult（已合併好的整包掃描結果，含 csharp_results、
    aspx_results、raw database invocations 與 inline SQL facts）。

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
    處理常式（如 btnDelete_Click）呼叫。這裡用「這個方法自己所屬的那個檔案」
    （不是整包 scan.csharp_results！）建一份反向呼叫關係（誰呼叫了誰），把
    「這個方法自己 + 所有會直接或間接呼叫到它的方法」一起拿去比對 UI 事件，
    才不會漏掉這種常見的多層呼叫情形。

    刻意把反向呼叫關係限縮在「同一個檔案」內建圖，而不是像早期版本那樣對整包
    scan.csharp_results 建一份全域反向呼叫圖：_method_adjacency 是純粹「以方法
    名稱」為 key 建鄰接表，完全沒有 class/檔案範圍限制——ASP.NET WebForms 專案
    裡 `BindData`/`Page_Load`/`btnSave_Click` 這類方法名稱在幾十個不同頁面裡
    重複出現是常態，若對整包 repo 建圖，A 頁面的 btnSave_Click 呼叫了它自己的
    BindData，會跟 B 頁面完全無關的 BindData 合併成同一個圖節點，導致 B 頁面
    的 ui_anchors 誤把 A 頁面的 btnSave_Click 也列進來（明明兩者的呼叫關係毫無
    關聯，只是方法名稱剛好相同）。限縮在同一檔案後，仍能正確處理「事件處理常式
    呼叫同頁面內的其他方法」這個常見情境，但不會再跨無關頁面誤配。
    """
    invocations = list(invocations)
    chains: List[dict] = []
    seen: Set[Tuple[str, str, str, str]] = set()
    method_nodes = MethodNodes(scan)
    rev_adj_cache: Dict[str, Dict[str, List[str]]] = {}
    screen_anchors = _screen_anchors_by_node(scan, root, program_screens)
    callers = _reverse_edges(_bound_call_graph(scan).edges) if screen_anchors else {}

    def _program_screen_anchors(node: str) -> List[dict]:
        """The Program Screens of each action that reaches `node` through Bound Call Targets."""
        if not screen_anchors:
            return []
        _, reached = _reachable_from([node], callers)
        return [anchor for caller in sorted(reached) for anchor in screen_anchors.get(caller, [])]

    def _rev_adj_for_file(csharp_file: str) -> Dict[str, List[str]]:
        if csharp_file not in rev_adj_cache:
            file_name = Path(csharp_file).name.lower()
            same_file = [fr for fr in scan.csharp_results if Path(fr.file_path).name.lower() == file_name]
            rev_adj_cache[csharp_file] = _reverse_method_adjacency(same_file)
        return rev_adj_cache[csharp_file]

    def add_chain(
        csharp_file: str,
        class_name: str,
        method_name: str,
        node: str,
        via: str,
        sp_name: str = "",
        access_record: Optional[Mapping[str, object]] = None,
        entry_method_name: str = "",
    ) -> None:
        # `node` is the method span that holds the access: two overloads are two chains.
        key = (csharp_file, class_name, method_name, node)
        if key in seen:
            return
        seen.add(key)
        rev_adj = _rev_adj_for_file(csharp_file)
        candidate_methods: Set[str] = set()
        for name in {method_name, entry_method_name} - {""}:
            candidate_methods |= {name} | _ancestors_of(name, rev_adj)
        ui_anchors = _find_ui_anchors_for_method(scan.aspx_results, candidate_methods, csharp_file)
        ui_anchors += _program_screen_anchors(node) if node else []
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
        if access_record:
            entry.update(
                {
                    "access_type": access_record.get("access_type", ""),
                    "path_id": access_record.get("path_id", ""),
                    "entry_method": access_record.get("entry_method", ""),
                    "sp_chain": list(access_record.get("sp_chain", []) or []),
                    "evidence": access_record.get("evidence", "unresolved"),
                    "reason": access_record.get("reason", ""),
                    "database": access_record.get("database", ""),
                    "database_candidates": list(
                        access_record.get("database_candidates", []) or []
                    ),
                    "database_attribution": access_record.get(
                        "database_attribution", "unresolved"
                    ),
                    "caller": access_record.get("caller", ""),
                    "caller_class": access_record.get("caller_class", ""),
                    "caller_method": access_record.get("caller_method", ""),
                    "procedure_name": access_record.get("procedure_name", ""),
                    "procedure_schema": access_record.get("procedure_schema", ""),
                    "branch_context": list(
                        access_record.get("branch_context", []) or []
                    ),
                    "source_span": dict(access_record.get("source_span", {}) or {}),
                    "source_snapshot_hash": str(
                        (access_record.get("source_span", {}) or {}).get(
                            "content_hash", ""
                        )
                    ),
                    "confirmed": access_record.get("confirmed", False),
                    "operation_type": access_record.get("operation_type", ""),
                    "conditions": list(access_record.get("conditions", []) or []),
                    "written_columns": list(access_record.get("written_columns", []) or []),
                    "reads": list(access_record.get("reads", []) or []),
                    "writes": list(access_record.get("writes", []) or []),
                }
            )
            entry.update(_wrapper_projection_fields(access_record))
        chains.append(entry)

    # 1) SQL-module access comes from the same Gateway + Execution Graph join as
    # find_by_table(). This preserves nested SP order and explicit read/write type.
    graph_accesses = (
        (
            filter_table_accesses(execution_paths, graph, table_name, access="all", database=database)
            if execution_paths is not None
            else query_table_accesses(graph, invocations, table_name, access="all", database=database)
        )
        if graph
        else []
    )
    for access_record in graph_accesses:
        if column_name and not _graph_access_matches_column(access_record, column_name):
            continue
        source_span = access_record.get("source_span") or {}
        relative_path = str(source_span.get("relative_path") or "")
        normalized_path = relative_path.replace("\\", "/").casefold()
        matching_files = [
            fr.file_path
            for fr in scan.csharp_results
            if _rel(fr.file_path, root).replace("\\", "/").casefold() == normalized_path
        ]
        if not matching_files:
            matching_files = [
                fr.file_path
                for fr in scan.csharp_results
                if Path(fr.file_path).name.casefold() == Path(relative_path).name.casefold()
            ]
        if len(matching_files) != 1:
            continue
        entry_method = str(access_record.get("entry_method") or "")
        entry_class, separator, entry_method_name = entry_method.rpartition(".")
        if not separator:
            entry_class, entry_method_name = "", entry_method
        # The chain names the method that holds the invocation, the same join that the
        # forward chain uses (see _caller_node). The entry method still finds the
        # WebForms control events of the page.
        class_name, method_name = _caller_names(access_record) or (entry_class, entry_method_name)
        sp_chain = list(access_record.get("sp_chain") or [])
        add_chain(
            matching_files[0],
            class_name,
            method_name,
            _caller_node(method_nodes, access_record),
            via="stored_procedure",
            sp_name=sp_chain[-1] if sp_chain else "",
            access_record=access_record,
            entry_method_name=entry_method_name,
        )

    # 2) Inline C# SQL remains a separate direct source fact. It does not infer
    # stored-procedure relationships and is never used to reconstruct SQL calls.
    # The by-table query gives the same answers as find_by_table(): it resolves an
    # unstated schema, it takes the Database from the rated invocation, and a read of
    # a View or a Function reaches the tables behind it in the graph.
    question = TableQuestion.of(table_name, database)
    # A request with no Database gives an empty graph here; `by_table` takes `None` for
    # it, so an inline read of a View or a Function gives only its direct answer.
    for answer in inline_table_relations.by_table(
        scan, question, invocations, root, graph or None, sql_cache_identity
    ):
        rel = answer.relation
        add_chain(
            rel.csharp_file,
            rel.class_name,
            rel.method_name,
            method_nodes.at_line(rel.csharp_file, rel.line_number),
            via="direct_sql",
        )

    return chains


def _graph_access_matches_column(access_record: Mapping[str, object], column_name: str) -> bool:
    """欄位層級的近似比對：在 graph 路徑中繼資料裡做純文字搜尋，不解析 SQL 語法樹。

    這是刻意的設計取捨：SELECT/WHERE/SET 子句要精準解析出「這裡真的是在動這個
    欄位」成本很高、也容易因為 T-SQL 語法變化而出錯；改用「欄位名稱是否以完整
    單字出現在路徑中繼資料（written_columns、conditions、reads、writes）裡」這種
    近似值。呼叫端（AI）在引用這個結果時應明確告知使用者這只是近似比對，不是保證。
    """
    haystack = " ".join(
        str(value)
        for field in ("written_columns", "conditions", "reads", "writes")
        for value in (access_record.get(field, []) or [])
    )
    return bool(re.search(r"\b" + re.escape(column_name) + r"\b", haystack, re.IGNORECASE))
