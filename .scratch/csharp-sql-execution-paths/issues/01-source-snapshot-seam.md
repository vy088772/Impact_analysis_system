# 01 — 建立 StaticAnalyzerHost、Gateway 與 source snapshot seam

**What to build:** 將 Roslyn 與 ScriptDom analyzer source projects 納入單一 StaticAnalyzerHost 建置與部署入口；Python 可驗證並呼叫該 host。掃描 C# 時保存目前 scan root 的最新完整檔案 snapshot，並讓 Gateway 以 content identity 與 source span 描述方法。

**Blocked by:** None — can start immediately.

**Status:** completed

- [x] 掃描結果能以穩定 identity 參照一份完整 C# 檔案 snapshot。
- [x] 方法 reference 能以 source span 還原完整方法內容。
- [x] refresh 會覆寫舊 snapshot，且每個 scan root 只保留最新版本。
- [x] 多個方法或路徑引用同一檔案時不複製完整 source text。
- [x] C# 與 SQL analyzer 可由同一 host 的不同命令執行，並回傳版本化 JSON contract。
- [x] source projects 納入專案；bin、obj 與 DLL 不作為 source-control 輸入，部署 artifact 才包含已建置 analyzer。
- [x] Python 在 host、.NET runtime 或 contract version 不可用時回傳明確錯誤。