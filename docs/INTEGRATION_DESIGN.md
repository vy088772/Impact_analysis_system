# 影響分析系統 — 整合架構設計書

> 目的：將 **llamaindex-spec-rag（規格書 RAG，大腦）** 與 **Impact_analysis_system（程式碼/DB 靜態分析，工具服務）** 串接成一條「RAG 優先」的問答 + 影響分析流水線。
>
> 狀態：**已實作完成（as-built）**。整合方式＝HTTP；兩專案各自獨立 `.venv`；spec-rag 為協調者，Impact 為純静態分析服務（不含 AI）。
>
> 實作狀態摘要：S1–S6 均完成並驗證。另增強：clone 進 `data/repos/<project>/<repo>` + 掃描快取 + `/refresh`；
> SP 完整定義擷取；完整方法片段 + 程式碼總量預算；embedding 語意檢索 + 逐函式注記；
> 程式化 grounding 驗證；RUN_AI / SEE_AI_PROMPT 等 .env 開關；互動式 CLI。詳見 §11。
>
> 核心流程（使用者構想）：
> ```
> 使用者自然語言提問
>   → RAG 找到對應規格書
>   → 從規格書萃取「程式名稱」
>   → 對這些程式做靜態程式碼分析（HTTP 呼叫 Impact 服務）
>   → 取得相關程式碼片段 / SP / Table
>   → 規格書業務說明 + 程式碼分析結果，一起丟 LLM 整合出答案
> ```

---

## 1. 目標與範圍

### 1.1 要達成的使用情境

```
輸入：一個變更點（SP 名 / Table 名 / 程式檔 / 需求描述）
輸出：
  - 影響範圍（哪些程式、SP、Table、功能畫面會被波及）
  - 風險評估（高/中/低 + 理由）
  - 建議方案（修改步驟、需回歸測試的功能）
  - AI 產出的變更規格書（Markdown / HTML）
```

### 1.2 對應目標 Pipeline 的覆蓋（RAG 優先版）

| 階段 | 由哪個元件負責 | 所在專案 | 新增 / 既有 |
|------|----------------|----------|------------|
| 1. 輸入（自然語言提問） | `app.py` / `chat.py`（既有） | spec-rag | 既有 |
| 4. 業務邏輯（找規格書） | RAG 查詢（既有） | spec-rag | 既有 |
| 1.5 萃取程式名稱 | `impact_orch/program_extractor.py` | spec-rag | **新增** |
| 2. 程式碼掃描 | `code_analyzer/*` | Impact 服務 | 既有 + 補調用鏈 |
| 3. 資料庫結構 | `sql_analyzer.py` + FK 擴充 | Impact 服務 | 既有 + 補 FK |
| — HTTP 介面 | `service/api.py`（FastAPI） | Impact 服務 | **新增** |
| 5. 收集 + 準備 Prompt | `impact_orch/context_builder.py` | spec-rag | **新增** |
| 6. AI 分析推理 | `impact_orch/ai_reasoner.py`（重用 RAG 的 LLM） | spec-rag | **新增** |
| 7. 輸出 | `impact_orch/output_writer.py` | spec-rag | **新增** |

---

## 2. 整體架構決策

### 2.1 三個關鍵決策（已確認）

1. **不合併，兩專案各自獨立 `.venv`**
   - spec-rag 需能**單獨執行**（它是主產品），不被 Impact 的依賴綁架。
   - 兩邊依賴差異大（Impact 用 `pyodbc/networkx`；RAG 用 `llama-index/chromadb/onnxruntime`）。

2. **整合方式＝HTTP（方案 B）**
   - Impact 系統包成 **FastAPI 服務**，對外提供 `POST /analyze`。
   - spec-rag 在「影響分析模式」用 HTTP client 呼叫；服務掛掉時退化為純 RAG。

3. **RAG 優先：spec-rag 是協調者（大腦），Impact 是工具服務**
   - **AI 推理集中在 spec-rag**，Impact 服務本身不含 AI。

### 2.2 架構圖（RAG 優先）

```
使用者自然語言提問
      │
      ▼
┌─────────── llamaindex-spec-rag（.venv #1，協調者/大腦）──────────┐
│  ① RAG 查詢 → 命中規格書 + 業務說明 + 命中系統名                  │
│  ② program_extractor → 從「命中規格書內文」萃取程式名            │
│  ③ rag_client ── HTTP POST /analyze {system, program_names} ─┐  │
│        ▲                                                     │  │
│        │   ┌── Impact_analysis_system（.venv #2，純分析服務）─▼┐ │
│        │   │ ③a system → Azure 專案映射 → azure_fetcher clone │ │
│        │   │ ③b smart_file_finder 依程式名定位檔案            │ │
│        │   │ ③c csharp/sql 分析 + 調用鏈 + FK + 片段          │ │
│        └───◄ JSON AnalyzeResponse ─────────────────────────────┘ │
│  ④ context_builder → 業務說明 + 程式碼分析                       │
│  ⑤ ai_reasoner → LLM（gpt-5.4）→ 整合答案/影響/風險/建議          │
│  ⑥ output_writer → 回答使用者 + md/html/json                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 端到端資料流（RAG 優先）

```
使用者自然語言提問（spec-rag）
  ↓ RAG 查詢（既有）
RagHit { answer, sources[], systems[] }      # 規格書命中 + 業務說明
  ↓ program_extractor
program_names[]                              # 從規格書/來源萃取的程式名
  ↓ rag_client.analyze(program_names)  ── HTTP ─► Impact 服務
                                                ↓ project_scanner / impact_analyzer
AnalyzeResponse {                            # Impact 服務回傳（純靜態，無 AI）
    programs[] {
        file, framework,
        methods[],                           # 類別/方法
        sql_queries[],
        stored_procedures[],                 # 呼叫的 SP
        tables[],                            # 讀寫的 Table（含 FK 連動）
        call_chains[],                       # 調用鏈
        code_snippets[]                      # 相關程式碼片段
    }
}
  ↓ context_builder
EnrichedContext { rag_answer, business_specs[], analysis: AnalyzeResponse }
  ↓ ai_reasoner（組 Prompt → LLM）
ReasoningResult {
    integrated_answer,          # 整合后的答案（主要輸出）
    impact_summary,             # 影響範圍
    risk { level, reasons[] },  # 風險評估
    recommendations[]           # 建議方案
}
  ↓ output_writer
spec-rag 則中回傳給使用者 + output/impact/<案件>_<時間>.{md,html,json}
```

> 表示圖示：**spec-rag 負責「問→規格書→程式名→整合→LLM」**；**Impact 服務只負責「程式名→靜態分析」**。

---

## 4. 檔案結構（as-built）

```
Impact_analysis_system/            【.venv #2】純靜態分析服務（不含 AI）
├── service/                        # HTTP 服務層
│   ├── api.py                       # FastAPI：GET /health、POST /analyze、POST /refresh
│   ├── schemas.py                   # 請求/回應 Pydantic 模型
│   ├── analyze_service.py           # 分析核心：來源解析 + 過濾程式 + 組裝回應
│   ├── repo_manager.py              # clone 進 data/repos/<project>/<repo>（refresh 才 pull）
│   ├── scan_store.py                # ProjectScanResult 持久化快取（data/scan_cache）
│   ├── snippet_extractor.py         # 依方法位置擷取完整方法本體
│   ├── call_chain_builder.py        # 程式內部方法呼叫鏈
│   ├── fk_resolver.py               # FK 連動資料表（sys.foreign_keys，盡力而為）
│   └── sp_fetcher.py                # 連資料庫擷取 SP 完整定義（盡力而為）
├── code_analyzer/                  # （現有解析器彙；sql_analyzer 由 sp_fetcher 重用）
├── config/settings.py              # 【擴充】SERVICE_HOST/PORT、AZURE_CLONE_ROOT、SCAN_CACHE_ROOT
├── data/repos/<project>/<repo>/    # clone 下來的原始碼
├── data/scan_cache/                # 持久化掃描快取（pickle）
└── main.py                         # （保留原有 CLI）

llamaindex-spec-rag/               【.venv #1】協調者 / 大腦（仍可單獨跑）
├── impact_orch/                    # 影響分析協調層
│   ├── program_extractor.py         # 從 RAG 命中結果萃取程式名（重用 _program_index）
│   ├── rag_client.py                # HTTP client → Impact /analyze、/refresh
│   ├── source_resolver.py           # system_id → catalog azure 來源 + database
│   ├── context_builder.py           # 組裝上下文（相關性篩選 + 總量預算 + SP 定義）
│   ├── code_retriever.py            # embedding 語意檢索 + 逐函式注記（雙層快取）
│   ├── ai_reasoner.py               # 組 Prompt → LLM（gpt-5.4）；build_prompt 不呼叫 LLM
│   ├── grounding.py                 # 程式化落地驗證（0 token 抓幻覺）
│   ├── output_writer.py             # 輸出 md / AI 輸入檔
│   ├── orchestrator.py              # 全流程串接 run_impact_analysis
│   ├── models.py                    # ProgramRef 等
│   └── run_cli.py                   # 互動式 CLI（免寫程式碼）
├── prompts/integrated_answer.txt    # 整合答案 Prompt 模板
├── query/chat.py                   # 【擴充】Chat.analyze_impact()
└── config.py                       # 【擴充】IMPACT_*、RUN_AI、SEE_AI_PROMPT、USE_CODE_* 等
```

> `storage/code_embeddings/`（程式碼向量 + 注記快取）與影響分析輸出報告，實際存放於
> `Impact_analysis_system/data/code_embeddings/` 與 `Impact_analysis_system/output/impact_analysis/`
> （屬於程式碼分析的衍生產物，放在 code 專案側，而非 spec-rag 自己的 `storage/`）。

---

## 5. 介面與資料合約（核心）

### 5.1 Impact 服務 HTTP API（Impact_analysis_system/service/api.py）

> FastAPI 服務。輸入程式名清單，回傳純靜態分析結果（**無 AI**）。

```
POST /analyze
Content-Type: application/json

請求：
{
  "system": "Y-Docs_TTPUR",         # RAG 命中的系統 id
  "source": {                       # spec-rag 由 system_catalog.json 解析後帶入
    "project": "System Dept 1",     # Azure DevOps 專案
    "repo": "Y-DOCs",               # 儲存庫（可多系統共用）
    "branch": "",                   # 留空用預設
    "path": "TTPUR"                 # repo 內子資料夾，區分同 repo 的多系統
  },
  "program_names": ["Sub_DeliveryDetail.aspx", "OrderService.cs"],
  "include_snippets": true,        # 是否回傳程式碼片段
  "include_sp_defs": false,        # 是否連資料庫回傳 SP 完整定義（需 DB）
  "fk_depth": 1,                   # FK 連動追蹤層數
  "database": "",                  # FK 查詢 / SP 擷取用資料庫簡稱（留空用預設）
  "refresh": false                 # true → git pull + 重新解析，覆寫快取
}

回應（AnalyzeResponse）：
{
  "programs": [
    {
      "program": "Sub_DeliveryDetail",
      "file": "...\\Sub_DeliveryDetail.aspx.cs",
      "framework": "WebForms",
      "methods": [{"name": "btnSave_Click", "class": "..."}],
      "stored_procedures": ["usp_PUR_OrderCompliance"],
      "tables": ["PUR_Order", "PUR_OrderDetail"],
      "related_tables": ["PUR_OrderHistory"],   # FK 連動的相關資料表
      "call_chains": [["btnSave_Click", "Save", "usp_PUR_OrderCompliance"]],
      "code_snippets": [{"file": "...", "label": "X.btnSave_Click", "lines": "120-156", "text": "..."}],
      "sp_definitions": [{"name": "...", "exists": true, "parameters": [], "tables": [], "complexity": "簡單", "definition": "..."}]
    }
  ],
  "not_found": [],                 # 找不到的程式名
  "source_root": "data/repos/System_Dept_1/Y-DOCs/TTPUR"
}

GET  /health   → {"status": "ok"}
POST /refresh  → {source_root, files, scope, partial, updated_files, removed_files, ...}
                  # body 可帶 program_names；空清單為 full system refresh

局部更新範例：
```json
{
  "system": "Y-Docs_TTPUR",
  "source": {"project": "System Dept 1", "repo": "Y-DOCs", "path": "TTPUR"},
  "program_names": ["Evaluate/PUR_MasterEdit.aspx"]
}
```

`program_names` 有值時，Impact 只替換對應 C#／view records 與該檔案的衍生 facts；
所有 scan roots 都必須已有目前版本的 cache；若 cache 過期、遺失或無法載入，
會回 HTTP 400 `program_refresh_requires_current_cache`，不會靜默回退為 full refresh。
請先不帶 `program_names` 執行一次完整 refresh，再重試局部更新。
SQL cache refresh 仍由 `/refresh_sql` 獨立處理。

CLI：
```powershell
python -m impact_orch.refresh_cli Y-Docs_TTPUR --program PUR_MasterEdit
python -m impact_orch.refresh_cli Y-Docs_TTPUR --program PUR_MasterEdit --program PUR_SOQry
```
```

**spec-rag 端呼叫（impact_orch/rag_client.py）：**
```python
import httpx
from config import cfg

def analyze(program_names: list[str], system: str, source: dict) -> dict:
    # source 由 spec-rag 從 system_catalog.json 的 azure 區塊解析後帶入
    r = httpx.post(
        f"{cfg.IMPACT_SERVICE_URL}/analyze",
        json={"system": system, "source": source,
              "program_names": program_names,
              "include_snippets": True, "fk_depth": 1},
        timeout=120,   # 首次需 clone Azure repo，預留較長
    )
    r.raise_for_status()
    return r.json()
```

> Impact 服務挂掉時，spec-rag 捕捉例外、跳過影響分析、仍回傳純 RAG 答案（graceful degradation）。

### 5.2 核心資料模型

**Impact 服務端（service/schemas.py，Pydantic）：**
```python
class AzureSource(BaseModel):
    project: str                      # Azure DevOps 專案
    repo: str                         # 儲存庫（可多系統共用）
    branch: str = ""                   # 留空用預設
    path: str = ""                     # repo 內子資料夾，區分同 repo 多系統

class AnalyzeRequest(BaseModel):
    system: str                       # RAG 命中的系統 id（僅供記錄/快取鍵）
    source: AzureSource               # spec-rag 由 catalog 解析後帶入
    program_names: list[str]
    include_snippets: bool = True
    fk_depth: int = 1

class ProgramAnalysis(BaseModel):
    file: str
    framework: str
    methods: list[dict]
    stored_procedures: list[str]
    tables: list[str]                 # 含 FK 連動
    call_chains: list[list[str]]
    code_snippets: list[dict]

class AnalyzeResponse(BaseModel):
    programs: list[ProgramAnalysis]
    not_found: list[str]
```

**spec-rag 協調端（impact_orch/models.py）：**
```python
@dataclass
class RagHit:
    answer: str                       # RAG 業務說明
    sources: list[dict]               # 命中規格書來源
    systems: list[str]                # 命中系統名

@dataclass
class RiskAssessment:
    level: str                        # "high" | "medium" | "low"
    reasons: list[str]

@dataclass
class ReasoningResult:
    integrated_answer: str            # 主要輸出：整合規格書+程式碼的答案
    impact_summary: str
    risk: RiskAssessment
    recommendations: list[str]
```

### 5.3 影響追蹤邏輯（code_analyzer/impact_analyzer.py，無 AI）

Impact 服務收到程式名清單後，針對這些程式做正向 + 反向追蹤：

```
程式名 → 定位檔案（smart_file_finder）→ 解析（csharp/aspx/...）
        → 該檔呼叫的 SP → SP 讀寫的 Table
                                      ↑ 沿 FK 把相連 Table 也納入（預設 1 層）
        → 調用鏈（caller → callee）
        → 擷取相關程式碼片段（snippet_extractor）
```

- 資料來源：`sp_relations`（SP↔C#）、`table_relations`（Table↔SP）、新增 `fk_relations`（Table↔Table）、新增 `call_chains`（method↔method）。
- **這一步不需要 AI，資料你已經幾乎都有**，只差 FK 與調用鏈兩塊（見 §6）。

### 5.4 原始碼來源解析（catalog 驅動，支援多系統共用 repo）

被分析的 .NET 原始碼由 Impact 服務從 **Azure DevOps** 取得。**來源映射是「多對一」**——一個 repo 可裝多個系統（例：repo `Y-DOCs` 同時含 `Y-Docs_TTPUR` 與 `Y-DOCs_TTRDQ`），故無法靠 repo 名稱自動推斷系統。

**設計決策：來源資訊標注在 `system_catalog.json` 每個系統的 `azure` 區塊**（spec-rag 的權威系統清單），而非 `.env` 的扁平映射：

```jsonc
// llamaindex-spec-rag/catalog/system_catalog.json
{
  "system_id": "Y-Docs_TTPUR",
  "doc_dir": "Y-Docs_TTPUR",
  "azure": { "project": "System Dept 1", "repo": "Y-DOCs", "branch": "", "path": "TTPUR" }
}
```

解析流程：
```
RAG 命中 system_id
  → spec-rag 從 catalog 取該系統 azure 區塊 → 組成 source{project,repo,branch,path}
  → 隨 /analyze 請求帶給 Impact 服務
  → Impact azure_fetcher clone/pull 對應 project/repo（org/PAT 在 Impact 自己的 .env）
  → 快取至本機 AZURE_CLONE_ROOT/<project>__<repo>/
  → 若 path 非空，限定在該子資料夾內以程式名定位（區分同 repo 多系統）
  → smart_file_finder 定位實際檔案 → 解析
```

- **權責分離**：路由（project/repo/branch/path）由 catalog 帶入；**機密（org/PAT）只留在 Impact 服務 `.env`**。
- `path` 子資料夾欄位是區分「同 repo 多系統」的關鍵；單一系統獨佔 repo 時留空即可。
- 快取鍵以 `project+repo` 為單位，多系統共用 repo 時只 clone 一次。
- 現有 [azure_fetcher.py](../code_analyzer/azure_fetcher.py) 已支援單 repo clone/pull + PAT，只需改為「依請求 source 指定 project/repo」。

---

## 6. 既有模組需要的擴充

### 6.1 Table 外鍵（sql_analyzer.py）
新增方法查 FK：
```sql
SELECT fk.name, tp.name AS parent_table, ref.name AS ref_table
FROM sys.foreign_keys fk
JOIN sys.tables tp  ON fk.parent_object_id = tp.object_id
JOIN sys.tables ref ON fk.referenced_object_id = ref.object_id;
```
→ 產出 `fk_relations: list[(table, ref_table)]`，寫入 `ProjectScanResult`。

### 6.2 方法調用鏈（csharp_parser.py + project_scanner.py）
- 既有 `MethodInfo.calls` 已抓到「方法呼叫了哪些名稱」。
- 擴充：掃描完成後做一次全域比對，把 callee 名稱解析回實際 `ClassInfo.MethodInfo`，建出 `call_graph: dict[method_id, list[method_id]]`。
- 用途：讓影響追蹤能從 SP 往上回溯到「哪個按鈕事件 / Controller action」。

---

## 7. Prompt 設計（impact_orch/prompts/，位於 spec-rag）

### 7.1 整合答案 Prompt（骨架）
```
你是資深系統分析師。使用者提了一個問題，系統已找到相關規格書與對應程式的靜態分析。
請結合「業務說明」與「程式碼實作」回答使用者，並輸出：
1) 整合答案（直接回答使用者問題，結合業務與程式實作）
2) 影響範圍摘要（涉及哪些程式/SP/Table）
3) 風險評估（high/medium/low + 理由）
4) 建議方案 / 需注意事項

【使用者問題】{user_question}
【規格書業務說明（RAG）】{rag_answer}
【相關程式這些來源】{program_names}
【程式靜態分析（SP/Table/調用鏈/片段）】{analysis}

請以繁體中文、條列、務實可執行的方式回答。
```

### 7.2 （選配）變更規格書 Prompt
以上述推理結果 + 業務說明，產出一份結構化 Markdown 規格書（變更目的 / 影響模組 / 資料異動 / 測試重點）。

---

## 8. 設定擴充

**Impact 服務端（Impact_analysis_system/.env）：**
```env
# === HTTP 服務 ===
SERVICE_HOST=127.0.0.1
SERVICE_PORT=8800

# === Azure DevOps （僅機密，路由由 catalog 隨請求帶入）===
AZURE_DEVOPS_ORG=topmost
AZURE_DEVOPS_PAT=***
# system → project/repo/path 映射不再放這裡，
# 改標注在 spec-rag/catalog/system_catalog.json 每個系統的 azure 區塊
AZURE_CLONE_ROOT=./data/repos
# （資料庫、SP 視則等沿用現有 settings.py）
```

**spec-rag 端（llamaindex-spec-rag/.env）：**
```env
# === 影響分析介面 ===
IMPACT_SERVICE_URL=http://127.0.0.1:8800   # Impact 服務位址
IMPACT_SERVICE_TIMEOUT=300
IMPACT_FK_DEPTH=1

# === AI 控制（AI 跑在 spec-rag）===
RUN_AI=false               # 是否呼叫 OpenAI 整合（false 省 token）
SEE_AI_PROMPT=true         # 寫出/顯示「送進 AI 的完整 prompt」

# === 內容品質 / 檢索（皆可選）===
INCLUDE_SP_DEFS=true       # 連資料庫擷 SP 完整定義
CONTEXT_MAX_CODE_CHARS=24000  # 送進 AI 的程式碼總量上限
USE_CODE_EMBEDDING=true    # embedding 語意檢索挑相關方法
CODE_EMBED_TOP_K=6
USE_CODE_ANNOTATION=false  # 逐函式注記後再檢索（一次性成本）
# OPENAI_API_KEY / OPENAI_MODEL / OPENAI_LOW_MODEL 重用現有 config.py
```

---

## 9. 實作階段（as-built，均已完成）

| 階段 | 內容 | 所在專案 | 狀態 |
|------|------|----------|------|
| **S1** | Impact FastAPI 服務：`service/api.py` `/health`、`/analyze` | Impact | ✅ |
| **S2a** | spec-rag：`program_extractor.py` 從 RAG 命中萃取程式名 | spec-rag | ✅ |
| **S2b** | Impact：`snippet_extractor.py` 擷取完整方法片段 | Impact | ✅ |
| **S3** | Impact：`call_chain_builder.py` 呼叫鏈 + `fk_resolver.py` FK 連動 | Impact | ✅ |
| **S4** | spec-rag：`rag_client.py` + `context_builder.py` + `source_resolver.py` | spec-rag | ✅ |
| **S5** | spec-rag：`ai_reasoner.py` + `prompts/integrated_answer.txt` | spec-rag | ✅ |
| **S6** | spec-rag：`output_writer.py` + `orchestrator.py` + `chat.analyze_impact()` + `run_cli.py` | spec-rag | ✅ |

> **先做 S1 + S2**（皆無 AI）：
> - S1 先讓 Impact 能以 HTTP 被呼叫、回傳正確分析。
> - S2a 驗證「RAG 能不能從規格書可靠地萃取出程式名」。
> - S2b 驗證「給程式名能不能拿到正確的 SP/Table/片段」。
> 這三點都可用現有資料驗證正確性，確認後再接 LLM，避免 AI 把錯誤資料放大。

---

## 10. 已確認決策

1. 整合方式：**HTTP（方案 B）**
2. 環境：**兩專案各自獨立 `.venv`**，spec-rag 仍可單獨跑
3. 流程：**RAG 優先**（問題→規格書→程式名→靜態分析→LLM 整合）
4. 角色：spec-rag = 協調者/大腦（含 AI）；Impact = 純靜態分析服務（無 AI）
5. 落地順序：**先 S1 + S2（無 AI 驗證）**
6. **程式名萃取來源**：從 RAG **「命中規格書內文」**萃取程式名
7. **原始碼來源**：從 **Azure DevOps** 取得；來源映射標注在 `system_catalog.json` 每個系統的 `azure` 區塊（**多系統可共用同一 repo，以 `path` 子資料夾區分**）；spec-rag 解析後隨請求帶入 `source`
8. **AI 模型**：重用 spec-rag 現有 `OPENAI_MODEL`（gpt-5.4）
9. **FK 連動深度**：預設 1 層（可由 `/analyze` 請求調整）
10. **服務埠**：Impact 服務預設 `127.0.0.1:8800`

---

## 11. 實作後增強（檢索與品質控制）

設計定案後，為了「送對的程式碼給 AI、控制 token、抓幻覺」，另外加入下列機制（皆在 spec-rag 端，由 .env 開關控制）：

| 機制 | 模組 | 作用 | 成本 |
|------|------|------|------|
| 來源 clone + 快取 | `service/repo_manager.py`、`scan_store.py` | 原始碼 clone 進 `data/repos/<project>/<repo>`；解析結果 pickle 快取，`refresh` 才重做 | 一次性 |
| SP 完整定義 | `service/sp_fetcher.py` | 連 DB 撈 SP 的 T-SQL、參數、引用表（揭露 C# 看不到的關聯表） | 需 DB |
| 完整片段 + 總量預算 | `context_builder.py`（`CONTEXT_MAX_CODE_CHARS`） | 方法送完整本體；全部程式碼總量設上限，大檔不撐爆 prompt | — |
| embedding 語意檢索 | `code_retriever.py`（`USE_CODE_EMBEDDING`） | 把方法向量化（建一次快取），依問題取最相關；中文也準 | 索引一次 + 每查 1 個 query embedding |
| 逐函式注記檢索 | `code_retriever.py`（`USE_CODE_ANNOTATION`） | 便宜模型把函式注記成一句話再檢索（summary for retrieval, code for generation）；逐函式雜湊快取，更新只重做有變動者 | 一次性注記 |
| 落地驗證 grounding | `grounding.py` | 程式化比對 AI 答案中的程式/SP/表是否真存在於靜態分析，標記可疑項 | 0 token |
| AI 開關 / 檢視 | `RUN_AI`、`SEE_AI_PROMPT` | 不跑 AI 也能組裝並寫出「送進 AI 的完整 prompt」供檢視 | 省 token |

> 設計原則延續「先驗證、再交給 AI」：可在 `RUN_AI=false`＋`SEE_AI_PROMPT=true` 下完整檢視送給 AI 的內容，確認無誤再開 AI。詳細操作見 [使用說明書 §9](使用說明書.md)。

---

## 下一步

S1–S6 均已實作並驗證。剩餘項目：

- 補齊 `system_catalog.json` 仍為空的系統 `azure` 區塊（gPurchase、SMICS、TPSI、YMTTeFinance、YMTTNAV）。
- （選配）將影響分析接進 Streamlit `app.py` UI。
- （選配）hybrid 檢索 + bge-reranker 重排；y語句改寫。
