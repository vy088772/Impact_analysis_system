# 03 — Shape decompiled facts into a contract-preflight snapshot proposal

**What to build:** The classified facts from a decompiled DLL (ticket 02) are shaped into an `Implementation Snapshot`-formatted proposal and exposed through `StaticAnalyzerHost`'s existing versioned console contract as an additive capability, so `ProjectScanResult.contract_preflight_proposals`/`contract_proposals` can be populated with it directly. Completeness is judged by reusing the existing `validate_implementation_snapshot` rules (identity fields, resolved method body/identity/argument roles/connection boundary/effective semantics/terminal sink for every relevant operation, no unresolved overloads, single assembly revision), plus one decompile-specific rule: any decompiler-reported translation problem for a relevant method makes the snapshot incomplete.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] The host's JSON response (`contract_version == 2`) carries a decompiled snapshot proposal in a shape that `_iter_scan_proposals()` already knows how to collect, with no change needed to `contract_preflight.py`
- [ ] A snapshot with every relevant operation fully resolved (body, identity, argument roles, connection boundary, effective semantics, terminal sink) and a single assembly revision is judged complete
- [ ] A snapshot with any unresolved overload, missing operation fact, or more than one assembly revision is judged incomplete, reusing the existing `validate_implementation_snapshot` failure reasons
- [ ] A snapshot where any relevant method has a decompiler-reported translation problem is judged incomplete for that reason specifically (distinguishable from the existing failure reasons)
- [ ] Unit tests exercise `validate_implementation_snapshot` (or its decompile-aware extension) directly against synthetic complete/incomplete/translation-failure snapshot shapes, following the existing pattern in `tests/test_refresh_contract_preflight.py`
