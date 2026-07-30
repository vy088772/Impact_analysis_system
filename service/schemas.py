# service/schemas.py
"""
影響分析服務的請求/回應資料模型（Pydantic）。

對應設計書 §5.1 / §5.2。所有欄位皆為純靜態分析結果，不含 AI 推理。
"""
from __future__ import annotations

from typing import List, Dict, Union
from pydantic import BaseModel, Field


class AzureSource(BaseModel):
    """原始碼來源（由 spec-rag 從 system_catalog.json 的 azure 區塊解析後帶入）。

    注意：repo_manager.ensure_repo() 一律以此來源 clone/沿用 data/repos/ 下的程式碼，
    不會退回本機 PROJECT_ROOT；repo 為空時會直接報錯。
    """
    project: str = ""        # Azure DevOps 專案（必填，不可留空）
    repo: str = ""           # 儲存庫（可多系統共用，必填）
    branch: str = ""         # 留空使用預設分支
    path: Union[str, List[str]] = ""
    # repo 內子資料夾，區分同 repo 的多系統；留空則整個 repo。
    # 若同一套系統的功能拆成多個 VS 專案資料夾（例如 Y-Docs_TTPUR 除了 TTPUR/
    # 外，還有 ATV/、Notification/、Response/ 這些屬於同一系統的兄弟資料夾），
    # 可傳入子資料夾清單，會一併掃描並合併成一個邏輯上的分析結果
    # （見 repo_manager.resolve_scan_roots() / analyze_service._merge_scans()）。


class AnalyzeRequest(BaseModel):
    """POST /analyze 請求。"""
    system: str = ""                         # RAG 命中的系統 id（僅供記錄/快取鍵）
    source: AzureSource = Field(default_factory=AzureSource)
    program_names: List[str]                 # 要分析的程式名清單
    include_snippets: bool = True            # 是否回傳程式碼片段（S2b 實作）
    include_sp_defs: bool = False            # 是否連資料庫擷取 SP 完整定義（需 DB 連線）
    fk_depth: int = 1                        # FK 連動追蹤層數（S3 實作）
    expand_depth: int = 0                    # 跨程式呼叫參照展開層數（0=不展開，向下相容）
    expand_max_programs: int = 10            # 展開時每支程式最多帶入幾個相關程式
    database: str = ""                        # 資料庫簡稱／快取鍵（通常是 spec-rag 的 system_id；留空則跳過 DB 相關功能）
    db_server: str = ""                       # 資料庫主機位址（由 catalog 逐系統提供；與 db_name 需同時提供）
    db_name: str = ""                         # 實際資料庫名稱（由 catalog 逐系統提供）
    refresh: bool = False                    # True → git pull + 重新解析，覆寫快取
    include_view_layer: bool = False         # 是否帶出 View 層資訊（aspx/razor/vue 解析摘要）


class CodeSnippet(BaseModel):
    file: str
    label: str = ""          # 片段標籤（類別.方法名 或 "file head"）
    lines: str = ""          # 例如 "120-156"
    text: str = ""


class ProgramAnalysis(BaseModel):
    """單一程式（檔案）的靜態分析結果。"""
    program: str                             # 對應請求的程式名
    file: str                                # 實際定位到的檔案路徑（相對 repo）
    framework: str = ""
    methods: List[Dict] = Field(default_factory=list)
    stored_procedures: List[str] = Field(default_factory=list)
    tables: List[str] = Field(default_factory=list)
    related_tables: List[str] = Field(default_factory=list)  # FK 連動的相關資料表（S3）
    call_chains: List[List[str]] = Field(default_factory=list)
    code_snippets: List[CodeSnippet] = Field(default_factory=list)
    sp_definitions: List[Dict] = Field(default_factory=list)  # SP 完整定義（include_sp_defs=True 時）
    view_definitions: List[Dict] = Field(default_factory=list)  # SQL View 完整定義（include_sp_defs=True 且表名實際為 View 時）
    udf_definitions: List[Dict] = Field(default_factory=list)  # UDF 完整定義（include_sp_defs=True 且程式 SQL 文字實際呼叫到該 UDF 時）
    dependencies: Dict[str, Dict] = Field(default_factory=dict)  # 物件上下游依賴（sys.sql_expression_dependencies，僅列出 sp_names/tables 中出現者，include_sp_defs=True 時）
    related_programs: List[Dict] = Field(default_factory=list)  # 跨程式呼叫展開（expand_depth>0 時）
    view_layer: List[Dict] = Field(default_factory=list)  # View 層資訊（include_view_layer=True 時；aspx/razor/vue 摘要）


class AnalyzeResponse(BaseModel):
    programs: List[ProgramAnalysis] = Field(default_factory=list)
    not_found: List[str] = Field(default_factory=list)
    source_root: str = ""                    # 實際分析的本機路徑（除錯用）


class RefreshRequest(BaseModel):
    """POST /refresh 請求：更新某系統的程式碼並重新解析。"""
    system: str = ""
    source: AzureSource = Field(default_factory=AzureSource)


class RefreshResponse(BaseModel):
    source_root: str = ""
    files: int = 0
    sp_relations: int = 0
    table_relations: int = 0


class FindBySPRequest(BaseModel):
    """POST /find_by_sp 請求：反查「哪些程式呼叫了這支 SP」（純快取比對，不觸發 clone）。

    cache_only=True（預設）時，若該 repo 尚未 clone 過，直接回傳 skipped=True，
    不會觸發 Azure clone —— 這支端點常被逐系統掃描式呼叫（不知道 SP 屬於哪個
    系統），避免對每個未分析過的系統都觸發一次昂貴的 clone。
    """
    source: AzureSource = Field(default_factory=AzureSource)
    sp_name: str                              # 要反查的 SP 名稱（不分大小寫比對）
    cache_only: bool = True                   # True → repo 未 clone 過就跳過，不觸發 clone
    refresh: bool = False                     # True → git pull + 重新解析（覆寫快取）後再比對


class SPMatchProgram(BaseModel):
    program: str = ""                         # 程式基底名（不含副檔名）
    file: str = ""                            # 相對 repo 根目錄的檔案路徑


class FindBySPResponse(BaseModel):
    sp_name: str = ""
    matches: List[SPMatchProgram] = Field(default_factory=list)
    skipped: bool = False                     # True：該 repo 尚未 clone/分析過，本次未比對
    source_root: str = ""                     # 實際比對的本機路徑（除錯用；skipped 時為空）


class FindByTableRequest(BaseModel):
    """POST /find_by_table 請求：反查「哪些程式存取了這張資料表」（純快取比對，不觸發 clone）。

    情境：使用者打算異動某張資料表（改欄位、改約束等），需要先知道哪些程式會受影響——
    這跟 FindBySPRequest 是同一種「反查」需求，只是比對對象從 sp_relations 換成
    table_relations。cache_only=True（預設）時，若該系統尚未分析過就直接跳過，不觸發
    clone（供逐系統嘗試反查時使用）。
    """
    source: AzureSource = Field(default_factory=AzureSource)
    table_name: str                           # 要反查的資料表名稱（可含或不含 schema 前綴，不分大小寫比對）
    cache_only: bool = True                   # True → repo 未 clone/分析過就跳過，不觸發 clone
    refresh: bool = False                     # True → git pull + 重新解析（覆寫快取）後再比對
    database: str = ""                        # 選填：資料庫快取鍵（通常是 spec-rag 的 system_id）。
    # 提供時會額外反查該系統已快取的 SP/View 定義本文——table_relations 只收錄
    # 「C# 程式碼內嵌 SQL 字串」直接出現的表名，若某張表只在被呼叫的 SP/View
    # 定義內部被引用（C# 端只呼叫 SP 名稱，未內嵌任何原始表名字串），純比對
    # table_relations 永遠找不到；留空則只做原本的 table_relations 比對。
    write_only: bool = False                  # True：只回傳「寫入」這張表的命中（access_type
    # 屬於 WRITE/WRITE_INDIRECT/INSERT/UPDATE/DELETE），濾掉純讀取（READ）與無法判斷（""）
    # 的命中——用於「打算異動這張表，只想知道誰會寫壞」這種比純反查更聚焦的情境。


class TableMatchProgram(BaseModel):
    program: str = ""                         # 程式基底名（不含副檔名）
    file: str = ""                             # 相對 repo 根目錄的檔案路徑
    via_sp: bool = False                       # True：這筆是透過「呼叫的 SP/View 定義本文有引用該表」間接找到的，
    # 不是 C# 程式碼裡直接內嵌該表名的原始命中（見 database 欄位說明）
    access_type: str = ""                     # 存取型態：C# 直接命中沿用 CSharpTableRelation.access_type
    # 既有的 "READ"/"INSERT"/"UPDATE"/"DELETE"；透過 write_dependencies 反查的 SP 命中為
    # "WRITE"/"READ"（DMF 只有 is_selected/is_updated 二元旗標，做不到動詞細緻度）；
    # 透過巢狀呼叫展開找到的間接命中為 "WRITE_INDIRECT"；查無資訊仍為 ""（未知，維持
    # 現行為，不代表「沒有寫入」）。


class FindByTableResponse(BaseModel):
    table_name: str = ""
    matches: List[TableMatchProgram] = Field(default_factory=list)
    skipped: bool = False                     # True：該 repo 尚未 clone/分析過，本次未比對
    source_root: str = ""                     # 實際比對的本機路徑（除錯用；skipped 時為空）


class RefreshSqlRequest(BaseModel):
    """POST /refresh_sql 請求：重新連線 SQL Server 撷取整庫 SP/View/Function/資料表
    Schema，覆寫本機快取（data/sql_cache/）。

    server/db_name 由呼叫端（spec-rag 的 catalog，逐系統標注）提供，不使用
    Impact 端 .env 的 DB_SERVER/DB_DATABASES；兩者缺一即報錯，不嘗試連線。
    """
    database: str                            # 快取鍵／顯示簡稱（通常是 spec-rag 的 system_id），必填
    server: str                              # 資料庫主機位址，必填
    db_name: str                             # 實際資料庫名稱，必填
    db_schema: str = "dbo"                    # SQL schema（欄位名稱不用 schema，避免與 BaseModel.schema() 名稱衝突）


class RefreshSqlResponse(BaseModel):
    database: str = ""
    db_schema: str = ""
    procedures: int = 0
    views: int = 0
    functions: int = 0
    tables: int = 0


class FlowChainRequest(BaseModel):
    """POST /flow_chain 請求：組出「關係鏈」候選清單（純靜態組裝，無 AI 判斷）。

    direction="forward"：從 anchor_method（program_name 內某個方法，通常是
    UI 事件處理常式）出發，走呼叫鏈到 SP、再到 SP 內部巢狀呼叫的其他 SP、
    最後彙整各層引用的資料表（含 FK 連動表）。program_name/anchor_method 必填。

    direction="backward"：從 table_name（可選 column_name，僅文字比對，非
    結構化保證）出發，反查引用該表的 SP、呼叫這些 SP（或直接用 SQL 存取此表）
    的 C# 方法、以及觸發該方法的 UI 控制項事件。table_name 必填，program_name/
    anchor_method 會被忽略。

    cache_only=True（預設）時，若該系統尚未 clone/分析過就直接跳過（與
    FindBySPRequest/FindByTableRequest 同樣的理由：這支端點也可能被逐系統
    嘗試呼叫），不觸發 Azure clone。
    """
    source: AzureSource = Field(default_factory=AzureSource)
    direction: str = "forward"                # "forward" | "backward"
    program_name: str = ""                    # forward 用：要分析的程式名
    anchor_method: str = ""                   # forward 用：錨點方法名稱
    table_name: str = ""                      # backward 用：資料表名稱
    column_name: str = ""                     # backward 用：欄位名稱（選填，近似文字比對）
    database: str = ""                        # 資料庫簡稱／快取鍵（通常是 spec-rag 的 system_id）
    db_server: str = ""                       # 資料庫主機位址（與 db_name 需同時提供）
    db_name: str = ""                         # 實際資料庫名稱
    max_sp_depth: int = 2                     # forward 用：SP 巢狀展開層數上限
    fk_depth: int = 1                         # forward 用：FK 連動追蹤層數
    cache_only: bool = True                   # True → 系統未 clone/分析過就跳過，不觸發 clone
    refresh: bool = False                     # True → git pull + 重新解析（覆寫快取）後再組鏈


class FlowChainResponse(BaseModel):
    direction: str = ""
    forward_chain: Union[Dict, None] = None   # direction=forward 時的結果（None 代表找不到錨點方法）
    backward_chains: List[Dict] = Field(default_factory=list)  # direction=backward 時的候選清單
    skipped: bool = False                     # True：該系統尚未 clone/分析過，本次未組鏈
    source_root: str = ""
