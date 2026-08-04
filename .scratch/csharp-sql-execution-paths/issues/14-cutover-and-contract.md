# 14 — 完成 cutover 並移除 legacy dependency sources

**What to build:** 在 Gateway、SQL graph、Path Selection 與 reverse lookup 驗收通過後，切換正式資料來源、提升 cache versions、拒絕 legacy cache，並移除舊 dependencies 與 regex formal-output 路徑。

**Blocked by:** 08 — 展開 nested SP 與 SQL branch paths；09 — 補齊 SQL lineage 與 typed object nodes；11 — 導入共用 Path Selection Loop；12 — 將 table reverse lookup 與 backward flow 遷移至 graph；13 — 產生 legacy-vs-Gateway migration report

**Status:** ready-for-agent

- [x] formal output 不再讀寫 dependencies、depends_on、depended_by 或 write_dependencies。
- [x] legacy regex detector 不再產生正式 SP relationships。
- [x] 舊 scan/SQL caches 被版本檢查拒絕並提示重新執行對應 refresh。
- [x] 完整 refresh、direct analysis、path selection、table lookup 與 backward flow smoke tests 通過。