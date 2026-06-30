# 影響分析系統 — 整合架構設計書

> 目的：將 **llamaindex-spec-rag（規格書 RAG，大腦）** 與 **Impact_analysis_system（程式碼/DB 靜態分析，工具服務）** 串接成一條「RAG 優先」的問答 + 影響分析流水線。
>
> 狀態：**v2 已確認方向**。整合方式＝HTTP；兩專案各自獨立 `.venv`；spec-rag 為協調者，Impact 為純靜態分析服務（不含 AI）。
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

## 4. 檔案結構（新增部分）

```
Impact_analysis_system/            【.venv #2】純靜態分析服務（不含 AI）
├── service/                        # 【新增】HTTP 服務層
│   ├── __init__.py
│   ├── api.py                       # FastAPI app：POST /analyze、GET /health
│   ├── schemas.py                   # 請求/回應 Pydantic 模型
│   └── analyze_service.py           # 串接 project_scanner + impact_analyzer
├── code_analyzer/
│   ├── impact_analyzer.py           # 【新增】反向影響追蹤（圖遍歷，無 AI）
│   ├── snippet_extractor.py         # 【新增】依程式名/方法定位並擷取程式碼片段
│   ├── csharp_parser.py             # 【擴充】方法調用鏈解析
│   ├── sql_analyzer.py              # 【擴充】FK 查詢
│   └── dependency_graph.py          # 【擴充】Table↔Table FK 圖
├── config/settings.py              # 【擴充】服務 host/port、program→file 映射設定
└── main.py                         # （保留原有 CLI；另可新增「啟動服務」選項）

llamaindex-spec-rag/               【.venv #1】協調者 / 大腦（仍可單獨跑）
├── impact_orch/                    # 【新增】影響分析協調層
│   ├── __init__.py
│   ├── program_extractor.py         # 從 RAG 命中結果萃取程式名（重用 _program_index）
│   ├── rag_client.py                # HTTP client → Impact 服務 POST /analyze
│   ├── context_builder.py           # 組裝 RAG 業務說明 + 分析結果
│   ├── ai_reasoner.py               # 組 Prompt → LLM（重用現有 OpenAI 設定）
│   ├── output_writer.py             # 輸出 md/html/json
│   ├── models.py                    # RagHit / AnalyzeResponse / ReasoningResult
│   └── prompts/
│       └── integrated_answer.txt    # 整合答案 + 影響/風險/建議 Prompt 模板
├── query/chat.py                   # 【擴充】新增「影響分析模式」分支
└── config.py                       # 【擴充】IMPACT_SERVICE_URL 設定
```

---

## 5. 介面與資料合約（核心）

### 5.1 Impact 服務 HTTP API（Impact_analysis_system/service/api.py）

> FastAPI 服務。輸入程式名清單，回傳純靜態分析結果（**無 AI**）。

```
POST /analyze
Content-Type: application/json

請求：
{
  "system": "gPurchase",            # RAG 命中的系統名（用來解析 Azure 專案）
  "program_names": ["Sub_DeliveryDetail.aspx", "OrderService.cs"],
  "include_snippets": true,        # 是否回傳程式碼片段
  "fk_depth": 1                    # FK 連動追蹤層數
}

回應（AnalyzeResponse）：
{
  "programs": [
    {
      "file": "...\\Sub_DeliveryDetail.aspx.cs",
      "framework": "WebForms",
      "methods": [{"name": "btnSave_Click", "class": "..."}],
      "stored_procedures": ["usp_PUR_OrderCompliance"],
      "tables": ["PUR_Order", "PUR_OrderDetail"],
      "call_chains": [["btnSave_Click", "Save", "usp_PUR_OrderCompliance"]],
      "code_snippets": [{"file": "...", "lines": "120-156", "text": "..."}]
    }
  ],
  "not_found": []                  # 找不到的程式名
}

GET /health  → {"status": "ok"}
```

**spec-rag 端呼叫（impact_orch/rag_client.py）：**
```python
import httpx
from config import cfg

def analyze(program_names: list[str], system: str) -> dict:
    r = httpx.post(
        f"{cfg.IMPACT_SERVICE_URL}/analyze",
        json={"system": system, "program_names": program_names,
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
class AnalyzeRequest(BaseModel):
    system: str                       # RAG 命中的系統名 → 解析 Azure 專案
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

### 5.4 原始碼來源解析（Azure DevOps 多專案）

被分析的 .NET 原始碼由 Impact 服務從 **Azure DevOps** 取得。因有**兩個 Azure DevOps 專案**，需先把「system name」對應到正確專案/儲存庫，再下載、定位程式檔：

```
system name（如 gPurchase / SMICS）
  → 查 AZURE_PROJECT_MAP（system → project:repo）
  → azure_fetcher clone/pull 對應 repo（擴充現有 azure_fetcher 為多專案）
  → 快取至本機 AZURE_CLONE_ROOT/<system>/
  → smart_file_finder 在 repo 內以程式名定位實際檔案
  → 解析
```

- 因此 `/analyze` 請求**必須帶 `system` 欄位**。
- 首次某個 system 會觸發 clone（較慢），之後快取重用、僅 `git pull`。
- 現有 [azure_fetcher.py](../code_analyzer/azure_fetcher.py) 已支援單專案 clone/pull + PAT，只需擴充為「依 system 查專案」。

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

# === Azure DevOps 多專案來源 ===
AZURE_DEVOPS_ORG=your-org
AZURE_DEVOPS_PAT=***
# system → project/repo 映射（逗號分隔多組）
AZURE_PROJECT_MAP=gPurchase:ProjectA/RepoA,SMICS:ProjectB/RepoB
AZURE_CLONE_ROOT=./data/repos
# （資料庫、SP 視則等沿用現有 settings.py）
```

**spec-rag 端（llamaindex-spec-rag/.env）：**
```env
# === 影響分析介面 ===
IMPACT_SERVICE_URL=http://127.0.0.1:8800   # Impact 服務位址
IMPACT_MODE_ENABLED=true                    # 關閉時退化為純 RAG
# OPENAI_API_KEY / OPENAI_MODEL 重用現有 config.py
```

---

## 9. 實作階段拆解（建議落地順序）

| 階段 | 內容 | 所在專案 | 是否需 AI |
|------|------|----------|-----------|
| **S1** | Impact 包成 FastAPI 服務：`service/api.py` `POST /analyze`（先回傳現有 SP/Table 分析） | Impact | 否 |
| **S2a** | spec-rag：`program_extractor.py` 從 RAG 命中萃取程式名（重用 `_program_index`） | spec-rag | 否 |
| **S2b** | Impact：`impact_analyzer.py` + `snippet_extractor.py` 反向追蹤 + 取片段 | Impact | 否 |
| **S3** | 補 FK（sql_analyzer）+ 調用鏈（csharp_parser），讓 /analyze 更完整 | Impact | 否 |
| **S4** | spec-rag：`rag_client.py` + `context_builder.py` 串接 HTTP | spec-rag | 否 |
| **S5** | spec-rag：`ai_reasoner.py` + prompts → 整合答案/風險/建議 | spec-rag | 是 |
| **S6** | spec-rag：`output_writer.py` + `chat.py` 「影響分析模式」分支 + UI | spec-rag | — |

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
7. **原始碼來源**：從 **Azure DevOps**（多專案）取得；以 `system → project/repo` 映射解析後 clone，再以程式名定位檔案
8. **AI 模型**：重用 spec-rag 現有 `OPENAI_MODEL`（gpt-5.4）
9. **FK 連動深度**：預設 1 層（可由 `/analyze` 請求調整）
10. **服務埠**：Impact 服務預設 `127.0.0.1:8800`

---

## 下一步

設計已定案。接下來從 **S1（Impact FastAPI 服務）** 開始實作，順序：S1 → S2a → S2b。

> 開工前需你提供（或確認）：
> - 兩個 Azure DevOps 專案實際的 **org / project / repo 名稱**，以及 **哪個 system 對應哪個專案**（填入 `AZURE_PROJECT_MAP`）。
> - Azure DevOps 的 **PAT**（請勿貼在對話中，直接寫進 `.env`）。
