# 04 — Branch-Aware Command Text and Embedded EXEC

**What to build:** 讓 Gateway 對 literal、有限 variable assignments 與 dynamic command text 做可解釋的分類。每個有限 branch value 都要保留其 predicate 與 provenance；inline SQL 中的 embedded `EXEC` 要作為額外 target evidence，而不能改變原本的 invocation mode。

**Blocked by:** 03 — Source-Backed Overload and Method Semantics.

**Status:** resolved

- [x] Variable 的 default assignment 與 conditional reassignment 會產生分開的 invocation candidates，不會只保留最後一個 textual assignment。
- [x] 每個 candidate 都保留 branch predicate、source span 與 value provenance，使不同 command text 能形成可解釋的 `Execution Path`。
- [x] leading whitespace 與 comments 後的 `SELECT`、`INSERT`、`UPDATE`、`DELETE`、`MERGE` 等 statement 會被分類為 `inline_sql`。
- [x] Text mode 的 `EXEC` 或 `EXECUTE` 會維持 `inline_sql`，並另外記錄 embedded procedure target 及其 Catalog validation 結果。
- [x] dynamic concatenation、external input、unbounded data flow、unknown argument 與 ambiguous assignment 會保留 `Unresolved Dynamic SQL` 或明確 unresolved reason，不會製造虛假的 target。
- [x] procedure-shaped prefix 沒有 explicit stored-procedure evidence 時只能作為弱候選提示，不能提升為 `proven`。

## Answer

Implemented branch-aware command-text classification across direct SqlClient, source/external wrappers, Dapper, and Entity Framework. Finite candidates now retain branch context, candidate source spans, and value provenance; incomplete candidate metadata fails closed. Inline SQL preserves its mode while embedded `EXEC` targets receive separate database-scoped Catalog evidence, including non-leading statements and unresolved sink paths. Procedure-shaped text without mode remains only a weak hint.

Validation: focused Gateway suite `120 passed`; StaticAnalyzerHost `dotnet build` passed. The repository-wide suite reached `271 passed` with two unrelated environment/schema failures: hard-coded Windows-path tests and a pre-existing formal-output edge assertion.
