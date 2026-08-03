# 05 — 自動解析 source-available database wrapper

**What to build:** 讓 Gateway 沿 source-available wrapper 的 method Flow 追到 ADO.NET sink，區分 stored-procedure mode 與 inline-SQL mode，並將 wrapper 呼叫串入正式 Execution Path。

**Blocked by:** 04 — 串起第一條 C# 到 DML 的 Execution Path

**Status:** ready-for-agent

- [x] wrapper 實作可追到 StoredProcedure sink 且 call site 選擇 SP mode 時產生 `proven` invocation。
- [x] 同一 wrapper 的 inline SQL mode 不會被判成 SP invocation。
- [x] wrapper 的 SP 名稱與 database source 會以對應 SP Catalog 驗證。
- [x] source 不可得時保留 unresolved evidence，不依永久 allowlist 假裝確定。