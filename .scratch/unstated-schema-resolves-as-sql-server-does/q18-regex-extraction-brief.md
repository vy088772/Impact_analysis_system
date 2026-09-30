# Q18 brief：regex 抽表的 CTE 與別名缺陷

這份說明可以直接貼到另一個 Claude Code session（工作目錄 `Impact_analysis_system`）。它是從 `unstated-schema-resolves-as-sql-server-does` 的 grilling 分出來的 Q18，那份 spec 把它列為 Out of Scope。

---

## 請你做的事

請先查證下面的事實，再用 grilling 的方式問我設計決定。不要改任何程式碼。

## 背景

這個 repo 用兩套機制從 SQL 文字找出「讀了哪些表、寫了哪些表」：

1. **Analyzer host**（C# 的 ScriptDom，`tools/StaticAnalyzerHost/SqlAnalyzer.cs`）：分析 SQL 快取裡 procedure／view／function 的定義，產生 SQL Execution Graph。
2. **Regex 抽取**：不經過 ScriptDom，用正規表達式從 SQL 文字抽表名。

`unstated-schema-resolves-as-sql-server-does` 會修正第 1 套機制的兩個缺陷：

- **CTE 被當成表**：`WITH X AS (...) SELECT ... FROM X` 被記成讀取一張叫 `X` 的表。本機七份快取有 231 筆。其中一筆（eFinance `EOR.AEBudgetLog_Summary_Qry` 的 CTE `Table1`）剛好跟真實的表 `test.Table1` 同名，所以 `/find_by_table test.Table1` 會回報一個假的讀取者。
- **UPDATE／DELETE 的別名被當成表**：`update B1 ... from BSPL.BudgetBalanceSheet B1` 被記成寫入 `B1`，真正的表只被記成讀取。本機有 330 筆，其中 80 筆藏住了真實表的寫入，所以 `write_only` 查詢會漏掉真正的寫入者。

**第 2 套機制（regex）很可能有同樣的缺陷，但這次不修。這份 brief 就是要查清楚它。**

## 三個 regex 抽取點

1. `code_analyzer/csharp_parser.py` 的 `_extract_tables_from_sql`（`_TABLE_PATTERNS`：`FROM`、`JOIN`、`INSERT INTO`、`UPDATE`、`DELETE FROM`）。
   - 用在 **C# 內嵌 SQL**。結果變成 `CSharpTableRelation`，存進 C# scan cache。
   - `/find_by_table` 的 inline 比對，以及 `flow_chain` 的 backward chain，都讀這些關聯。
2. `code_analyzer/sql_analyzer.py` 的 `_quick_extract_tables`（`FROM`、`JOIN`、`INTO`、`UPDATE`）。
   - `quick_analyze_sp` 在原生依賴查詢（`sys.dm_sql_referenced_entities`）失敗或查不到結果時，改用它。
   - `estimate_complexity_from_definition` 也呼叫它。
3. `sql_analyzer.extract_tables_from_definition`，它是第 2 點的包裝。
   - `service/flow_chain_builder.py` 用它，從可達方法的 `MethodInfo.sql_queries` 抽表名。

## 可能的缺陷（請逐一查證）

- **CTE**：`WITH X AS (...) SELECT ... FROM X`，`FROM X` 會被 `FROM` pattern 抓成表。
- **UPDATE 別名**：`UPDATE o SET ... FROM dbo.Orders o`，`UPDATE` pattern 抓到 `o`。
- **DELETE 別名**：`DELETE o FROM dbo.Orders o`，`DELETE FROM` pattern 抓不到目標 `o`；`FROM dbo.Orders` 會被 `FROM` pattern 抓到。所以真實的表有被找到，但讀寫的區分可能不對。
- **讀寫區分**：`CSharpTableRelation` 的 `access_type` 是整個語句的類型（`READ`／`INSERT`／`UPDATE`／`DELETE`），不是每張表各自的類型。一個 `UPDATE ... FROM A JOIN B` 可能讓 A、B 都被標成 `UPDATE`。
- **其他 regex 誤判**：例如 `FROM` 後面接子查詢、`OUTER APPLY`、`MERGE`、字串裡的 SQL 關鍵字、註解（第 1 點有沒有先移除註解？）。

## 請查證的事實（用真實資料）

- C# scan cache 在 `data/scan_cache/`（pickle，讀取方式見 `service/scan_store.py`；`evaluation` 端有 `_RestrictedScanCacheUnpickler` 的例子）。請數：
  - 所有 `CSharpTableRelation` 裡，表名等於同一段 SQL 裡某個 CTE 名稱的有幾筆。
  - 表名等於同一段 SQL 裡某個別名的有幾筆。
  - 這些誤判裡，有幾筆剛好跟某個 SQL 快取列出的真實表同名，因此會讓 `/find_by_table` 回報錯誤的答案。
- `quick_analyze_sp` 的 regex fallback 實際多常被用到？（原生依賴查詢要連線，本機沒有 ODBC driver；它的結果存在哪裡、被誰讀？）
- `flow_chain_builder` 那條路徑的輸出，會被哪個 API 回傳？

## 請問我的設計決定（grilling）

查完事實之後，至少要涵蓋這些分支：

1. regex 抽取要**修補**（例如先抓出 CTE 名稱和別名再排除），還是**改用 ScriptDom**（把 C# 內嵌 SQL 也送進 analyzer host）？各自的成本和風險。
2. 如果改用 ScriptDom：C# 內嵌 SQL 常常是字串拼接出來的片段，不是完整的語句，ScriptDom 解析失敗時怎麼退回？
3. 讀寫區分要不要改成每張表各自的類型？這會不會改變 `CSharpTableRelation` 的格式、C# scan cache 的版本，以及需不需要重新掃描？
4. 跟 `unstated-schema-resolves-as-sql-server-does` 的關係：C# 內嵌 SQL 沒寫 schema 的表會解析成 `dbo`（用 Object Location Index 判斷 `dbo.name` 在不在）。如果 CTE 名稱或別名先被誤當成表，這條規則會拿錯的名字去查。兩個功能誰要先做？
5. `quick_analyze_sp` 的 fallback 和 `flow_chain_builder` 那條路徑：要一起修，還是只修 C# 內嵌 SQL？

## 相關文件

- `.scratch/unstated-schema-resolves-as-sql-server-does/spec.md`（這次的 spec）
- `.scratch/canonical-object-identity/spec.md` 的 Out of Scope（最早記錄 CTE 和別名缺陷的地方，ticket 06 的 `ecda5f8`）
- `CONTEXT.md`、`docs/adr/0035-an-unproven-schema-marks-one-execution-path.md`
- 使用者的 memory 原則：少報比多報嚴重；通用規則優先於逐系統微調；行為描述要對照程式碼。
