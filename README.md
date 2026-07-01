# Impact Analysis System

靜態程式碼掃描與影響分析系統，用於分析 C#、ASPX、Razor、Vue 等多種技術棧專案的依賴關係、資料庫連線及預存程序呼叫。可從本機路徑或 **Azure DevOps 儲存庫** 取得原始碼，自動辨識技術棧、追蹤資料庫連線、解析預存程序（SP）呼叫，並輸出互動式依賴關係圖與 HTML 報告。
本系統提供兩種使用方式：

1. **互動式 CLI**（`main.py`）— 完整的本機掃描、智慧搜尋、依賴圖與 SP 深度分析。
2. **FastAPI 影響分析服務**（`service/`）— 無 AI 的 HTTP 服務，供上游 RAG 大腦（[llamaindex-spec-rag](../llamaindex-spec-rag)）依「規格書 → 程式名 → 静態分析 → AI 整合」流程呼叫。服務會將原始碼 clone 進 `data/` 並快取解析結果，避免重複掃描。

> 📖 完整端到端操作步驟請參考 [使用說明書](docs/使用說明書.md)。
## 功能特色

- **多框架支援**：自動偵測並解析 ASP.NET WebForms（ASPX/ASCX）、ASP.NET MVC（Razor/CSHTML）、ASP.NET Core、Web API、Vue.js 單檔元件
- **多語言解析器**：C#、ASPX、Razor、Vue 各有專屬解析器，提取類別、方法、API 端點、控制項、事件處理、HTML/Tag Helpers 等
- **SQL 與 SP 分析**：從 C# 字串字面值提取 SQL 查詢，並透過可設定的規則（封裝方法名、`CommandType.StoredProcedure`、`EXEC`）偵測預存程序呼叫
- **資料庫連線追蹤**：辨識「哪個變數連到哪個資料庫」，支援 `SQLFunc`、`GetConnectionString`、`ConfigurationManager.ConnectionStrings`、EF Core `DbContext` 注入四種模式
- **自動偵測資料庫設定**：掃描前自動讀取目標專案的 `web.config` / `appsettings.json` 連線字串，動態注入設定，無需在 `.env` 預先列出所有資料庫
- **多資料庫同時連線**：SP 來源未知時，自動跨所有已連線資料庫搜尋，並利用已知 SP 的資料表歸屬反推未知資料庫
- **預存程序深度分析**：連接 MS SQL Server 取得 SP 定義、參數、涉及資料表，偵測動態 SQL、暫存表、游標、交易，並估算複雜度
- **依賴關係圖**：以 NetworkX + matplotlib 產生 C#→SP、SP→Table、完整三層依賴圖、Top N 熱門 SP、高影響力節點等多種圖表，並輸出可拖曳縮放的互動式 HTML
- **規模自適應**：依節點數量自動選擇完整圖 / 簡化圖 / 僅摘要圖三種策略
- **智慧搜尋**：依名稱關鍵字搜尋所有相關格式檔案（aspx/cs/cshtml/vue/controller/service），並列出其呼叫的 SP 與資料表
- **報告產生**：輸出含 Chart.js 圖表的互動式 HTML 報告，以及 JSON / Excel 格式的 SP 分析結果
- **Azure DevOps 整合**：以 PAT 認證自動 `git clone` / `git pull` 目標儲存庫（shallow clone），PAT 在輸出中自動遮蓋
- **HTTP 影響分析服務**：以 FastAPI 提供 `/analyze`、`/refresh` 端點，依程式名回傳方法、SP、資料表、FK 連動、呼叫鏈與程式碼片段；可選連資料庫回傳 **SP 完整定義**；原始碼一律 clone 進 `data/`，解析結果持久化快取，更新指令才重新解析

## 系統需求

- Python 3.9+
- MS SQL Server（搭配 ODBC Driver 17 for SQL Server）
- Windows 作業系統（預設 Windows 驗證模式，亦支援 SQL 驗證）
- Git（使用 Azure DevOps 自動取得原始碼時需要）
- FastAPI + Uvicorn（啟用 HTTP 影響分析服務時需要）

## 安裝

### 1. 建立虛擬環境

```bash
python -m venv venv
venv\Scripts\activate
```

### 2. 安裝相依套件

```bash
pip install -r requirements.txt
```

或手動安裝核心套件：

```bash
pip install beautifulsoup4 sqlparse pandas openpyxl networkx matplotlib tqdm colorama python-dotenv pyodbc regex fastapi uvicorn pydantic
```

### 3. 設定環境變數

在專案根目錄建立 `.env` 檔案（可參考 `.env.example`），主要設定如下：

```env
# === 執行環境 ===
ENVIRONMENT=development

# === 資料庫伺服器 ===
DB_SERVER=your-server-name
DB_PORT=1433
DB_AUTH_MODE=windows            # windows 或 sql
DB_USER_ID=                     # SQL 驗證時填寫
DB_PASSWORD=                    # SQL 驗證時填寫
DB_DRIVER=ODBC Driver 17 for SQL Server

# === 多資料庫（alias:dbname 以逗號分隔）===
DB_DATABASES=STC:STC_DB,PUR:PUR_DB
DB_DEFAULT_DATABASE=STC

# === 專案掃描 ===
PROJECT_ROOT=D:\YourProject
EXCLUDE_FOLDERS=bin,obj,packages,node_modules,.git,.vs
EXCLUDE_PATTERNS=*.Designer.cs,*.g.cs,*.g.i.cs

# === Azure DevOps（選用，從遠端儲存庫取得原始碼）===
AZURE_DEVOPS_ORG=
AZURE_DEVOPS_PROJECT=
AZURE_DEVOPS_REPO=
AZURE_DEVOPS_PAT=
AZURE_DEVOPS_BRANCH=main
AZURE_DEVOPS_CLONE_DIR=          # 留空則使用暫存目錄

# === 影響分析服務（FastAPI）===
SERVICE_HOST=127.0.0.1
SERVICE_PORT=8800
AZURE_CLONE_ROOT=./data/repos    # 原始碼 clone 根目錄（依 project/repo 分層）
SCAN_CACHE_ROOT=./data/scan_cache  # 静態掃描快取根目錄

# === 輸出 ===
OUTPUT_DIR=output
GENERATE_CHARTS=True
GENERATE_HTML_REPORT=True

# === 日誌 ===
LOG_LEVEL=INFO
LOG_FILE=logs/analysis.log
```

> 完整設定項請參考 [config/settings.py](config/settings.py)。

## 使用方式

### 啟動主選單

```bash
python main.py
```

選單選項：

| 選項 | 功能 |
|------|------|
| 1 | **測試設定** — 印出所有設定值並驗證 .env（資料庫、路徑、驗證模式），列出錯誤 |
| 2 | **掃描專案** — 選擇原始碼來源（手動路徑 / `.env` / Azure DevOps）後執行完整掃描，含 SP 分析與摘要 |
| 3 | **智慧搜尋** — 輸入模組名稱，找出所有相關檔案並列出其呼叫的 SP 與涉及資料表 |
| 4 | **生成依賴關係圖** — 互動式選擇測試 / 完整 / 單一模組，輸出 PNG 與互動式 HTML 圖表 |
| 5 | **分析預存程序** — 選擇資料庫後可單一 SP 分析、批次分析全部 SP、顯示資料庫摘要 |
| 0 | 離開 |

### 原始碼來源（掃描時可選）

1. **手動輸入** 本機專案路徑
2. 讀取 `.env` 的 `PROJECT_ROOT`
3. **從 Azure DevOps 自動 clone**（以 PAT 認證，shallow clone；已存在則 `git pull`）

## 影響分析服務（FastAPI，供 spec-rag 呼叫）

`service/` 提供一個**無 AI** 的 HTTP 服務，供上游 RAG 大腦（llamaindex-spec-rag）協調呼叫。職責是「給程式名 → 回傳静態分析」，AI 整合由 spec-rag 負責。

### 啟動

```bash
# 方式一
uvicorn service.api:app --host 127.0.0.1 --port 8800
# 方式二
python -m service.api
```

### 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/health` | 健康檢查，回 `{"status": "ok"}` |
| POST | `/analyze` | 依 `program_names` 回傳每支程式的檔案/框架/方法/SP/資料表/FK 連動表/呼叫鏈/程式碼片段 |
| POST | `/refresh` | 更新指令：git pull 取最新程式碼並重新解析，覆寫快取 |

`POST /analyze` 請求主要欄位：

```jsonc
{
  "system": "Y-Docs_TTPUR",          // 系統 id（記錄/快取用）
  "source": {                         // 由 spec-rag 從 catalog 帶入
    "project": "System Dept 1",
    "repo": "Y-DOCs",
    "branch": "",                     // 留空用預設分支
    "path": "TTPUR"                   // repo 內子資料夾（多系統共用 repo）
  },
  "program_names": ["PUR_CostUpload", "PUR_YMMCPriceImport.aspx"],
  "include_snippets": true,           // 是否回傳程式碼片段
  "include_sp_defs": false,           // 是否連資料庫擷取 SP 完整定義（需 DB）
  "fk_depth": 1,                      // FK 連動追蹤層數
  "database": "",                     // FK 查詢 / SP 擷取用資料庫簡稱（留空用預設）
  "refresh": false                    // true → git pull + 重新解析
}
```

### 來源管理：clone 進 `data/`

服務**不讀取任意本機路徑**，而是依 `source` 將原始碼集中管理在：

```
data/repos/<project>/<repo>/        # 對應 Azure DevOps 的 org/project/_git/repo 階層
```

- 首次分析：若目錄不存在 → 從 Azure DevOps clone。
- 之後：直接沿用已 clone 的副本，**不**自動 `git pull`。
- 只有 `refresh=true`（或 `POST /refresh`）才 `git pull` 取最新。
- 多系統共用同一 repo 時，以 `source.path` 子資料夾區分（如 `Y-DOCs/TTPUR`、`Y-DOCs/TTRDQ`）。

### 解析快取（避免重複掃描）

首次掃描某路徑後，`ProjectScanResult` 以 pickle 持久化至：

```
data/scan_cache/<hash>.pkl          # 掃描結果
data/scan_cache/<hash>.meta.json    # 快取版本與時間
```

- 之後的 `/analyze` 直接載入快取（秒回），**不**重新解析 C#。
- `refresh=true` 才會重新掃描並覆寫快取。
- 含記憶體 + 磁碟雙層快取；模型結構變動時可遞增快取版本碼使舊快取自動失效。

> 備註：服務以 `analyze_sp=False` 掃描（不連資料庫）；FK 連動表為「盡力而為」，無資料庫或無 FK 時回傳空。

## 專案結構

```
Impact_analysis_system/
├── main.py                    # 主程式入口（互動式選單）
├── requirements.txt           # 相依套件清單
├── code_analyzer/             # 核心分析模組
│   ├── models.py              # 資料模型（FileType / ClassInfo / SQLQuery / StoredProcedureCall 等）
│   ├── csharp_parser.py       # C# 解析器（類別、方法、SQL、SP 呼叫、API 端點）
│   ├── aspx_parser.py         # ASP.NET WebForms 解析器（指示詞、控制項、事件、Code-behind）
│   ├── razor_parser.py        # Razor/MVC 視圖解析器（@model、HTML/Tag Helpers、程式碼區塊）
│   ├── vue_parser.py          # Vue.js 解析器（template/script/style、props、API 呼叫）
│   ├── sql_analyzer.py        # SQL 與 SP 深度分析器（連 SQL Server、複雜度評分、Excel 匯出）
│   ├── db_connection_tracker.py  # 資料庫連線追蹤（變數 → 資料庫對應）
│   ├── config_parser.py       # web.config / appsettings.json 連線字串解析
│   ├── project_type_detector.py  # 專案類型 / 技術棧自動偵測
│   ├── project_scanner.py     # 專案掃描主協調器（整合所有解析器與 SP 分析）
│   ├── smart_file_finder.py   # 依名稱智慧搜尋相關檔案
│   ├── dependency_graph.py    # 依賴關係圖與統計圖表產生器
│   ├── report_generator.py    # 互動式 HTML 報告產生器（Chart.js）
│   └── azure_fetcher.py       # Azure DevOps git clone / pull（PAT 認證）
├── config/                    # 設定模組
│   ├── settings.py            # 系統設定（資料庫、路徑、Azure、輸出、日誌、服務、快取）
│   ├── sp_detection_rules.json  # 預存程序偵測規則
│   └── sp_detector_config.py  # SP 偵測規則載入與編譯
├── service/                   # FastAPI 影響分析服務（無 AI）
│   ├── api.py                 # FastAPI app：/health、/analyze、/refresh
│   ├── schemas.py             # 請求/回應資料模型（Pydantic）
│   ├── analyze_service.py     # 分析核心：來源解析 + 過濾程式 + 組裝回應
│   ├── repo_manager.py        # clone 進 data/repos/<project>/<repo>（refresh 才 pull）
│   ├── scan_store.py          # 掃描結果持久化快取（data/scan_cache）
│   ├── snippet_extractor.py   # 依方法位置擷取程式碼片段
│   ├── call_chain_builder.py  # 程式內部方法呼叫鏈
│   ├── fk_resolver.py         # FK 連動資料表解析（盡力而為）
│   └── sp_fetcher.py          # 連資料庫擷取 SP 完整定義（盡力而為）
├── tests/                     # 測試腳本
├── data/                      # 服務用資料
│   ├── repos/                 # clone 下來的原始碼（依 project/repo 分層）
│   └── scan_cache/            # 持久化的静態掃描快取（pickle）
├── output/                    # 輸出目錄
│   ├── reports/               # 互動式 HTML 分析報告
│   ├── graphs/                # 互動式依賴關係圖（HTML/PNG）
│   ├── charts/                # 統計圖表
│   ├── project_scan/          # 專案掃描結果
│   └── sp_analysis/           # 預存程序分析結果（JSON）
└── logs/                      # 執行記錄
```

## 解析能力一覽

| 解析器 | 對象 | 提取內容 |
|--------|------|----------|
| `CSharpParser` | `.cs` | namespace、using、類別/繼承/介面、方法（async/static/virtual/override 等）、SQL 查詢、SP 呼叫、API 端點（Route/HttpVerb/Authorize）、行數統計 |
| `ASPXParser` | `.aspx` / `.ascx` | Page/Control 指示詞、ASP.NET 控制項、事件處理（OnClick…）、Code-behind 對應、內嵌程式碼警告 |
| `RazorParser` | `.cshtml` | `@model`/`@using`/`@inject` 等指示詞、`@{}` 程式碼區塊、HTML Helpers、Core Tag Helpers、內嵌 SQL 警告 |
| `VueParser` | `.vue` | template/script/style 區塊、props/data/computed/methods/lifecycle、axios/fetch/\$http API 呼叫 |

## 預存程序偵測規則

SP 呼叫偵測由 [config/sp_detection_rules.json](config/sp_detection_rules.json) 驅動，可自訂：

- **`wrapper_methods`**：自訂 DB 封裝方法名稱（如 `ExeProcRead`、`CreateReader`、`ExecuteStoredProcedureAsync` 等）
- **`sp_name_patterns`**：SP 命名規則 regex（如 `^sp[A-Z_]`、`^usp[A-Z_]`）
- **`detect_command_type`**：偵測 `CommandType.StoredProcedure`
- **`detect_exec_statements`**：偵測直接 `EXEC` / `EXECUTE`

SP 深度分析會偵測動態 SQL、暫存表（`#table`）、游標、交易，並依此估算複雜度（簡單 / 中等 / 複雜）。

## 輸出說明

| 輸出類型 | 路徑 | 說明 |
|----------|------|------|
| HTML 報告 | `output/reports/` | 含摘要卡片、複雜度分布、各資料庫統計、SP 與資料表清單、檔案清單（Chart.js 互動圖表） |
| 依賴圖 | `output/graphs/` | 互動式 HTML（可拖曳/縮放）+ PNG，含 C#→SP、SP→Table、完整依賴、Top N、高影響力節點 |
| 統計圖表 | `output/charts/` | 複雜度分布、資料庫比較、SP 熱門排行等 matplotlib 圖表 |
| SP 分析 | `output/sp_analysis/` | JSON 格式的預存程序詳細分析（亦可匯出 Excel） |

## 版本資訊

- **版本**：1.0.0
- **作者**：Yuhsien Tseng
- **授權**：MIT
