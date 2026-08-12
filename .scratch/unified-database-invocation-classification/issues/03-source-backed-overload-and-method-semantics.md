# 03 — Source-Backed Overload and Method Semantics

**What to build:** 讓 `CSharpAnalysisGateway` 先透過 `Receiver Implementation Binding` 找到 concrete implementation，再以 source implementation 或可接受的 implementation evidence 決定 wrapper method 的實際 semantics，而不是以 method name、receiver type name 或 procedure prefix 猜測。Overload identity 必須足以區分同名但不同資料庫行為的 methods。

**Blocked by:** 01 — Direct Text Database Invocation; 02 — Catalog-Validated Stored-Procedure Invocation; existing `csharp-sql-execution-paths` 05 — Source Wrapper Discovery.

**Status:** resolved

- [x] `Receiver Implementation Binding` 會沿著 receiver expression、construction 與 relevant assignments 解析 concrete implementation；可取得時保留 exact assembly identity 與 assembly revision，receiver type name 單獨不能選擇 contract 或 overload。
- [x] 每個可分類的 method 都保留 bound implementation、receiver type、method name、arity 與可取得的 parameter types，並以這些 facts 選擇 overload。
- [x] Source implementation 能區分 fixed `CommandType.Text`、fixed `CommandType.StoredProcedure`、call-site selected 與 unresolved method semantics。
- [x] fixed Text implementation 即使 command text 以 `sp`、`usp` 或 `proc` 開頭，也維持 `inline_sql`；method name 或 prefix 不得單獨產生 stored-procedure evidence。
- [x] fixed Stored Procedure implementation 只有在 target finite 且 terminal sink 已知時，才進入 stored-procedure classification。
- [x] 無法唯一選擇 overload 時保留所有候選、source provenance 與 `ambiguous_overload` reason，不得依 registry order 或 method name 任意選擇。
- [x] Source-backed SQLObject fixture 能驗證 text-mode reader/scalar/edit、fixed stored-procedure reader/non-query、call-site semantics 與 concrete receiver binding。

## Comments

- Added source-backed receiver implementation binding, construction/assignment provenance, method identity/arity/parameter types, overload selection, and fail-closed `ambiguous_overload` handling.
- Added fixed Text, fixed Stored Procedure, call-site, unresolved, procedure-shaped Text, strict terminal-sink, and real `SqlDataAdapter.Fill` coverage through the SQLObject fixture.
- Source-backed classification now fails closed when method semantics or concrete receiver binding is absent; overload matching uses qualified type identity, cross-method receiver assignments are retained, and refresh/discovery grouping preserves implementation/method facts.
- Review hardening: source-wrapper method identities include parameter types; unresolved source wrappers cannot fall through to Dapper/EF adapter detection; methods containing multiple `SqlCommand` instances are explicitly unresolved with `multiple_sql_commands`; partial-class receiver assignments are searched across the source roots; unused command-text scaffolding was removed.
- Validation: isolated `dotnet build tools\\StaticAnalyzerHost\\StaticAnalyzerHost.csproj --no-restore -p:OutDir=bin\\Debug\\isolated\\` succeeded; Python `py_compile` and VS Code diagnostics reported no errors; Gateway suite `103 passed`; downstream consumer suite `64 passed`; focused external precedence tests `3 passed`; focused host-to-Gateway tests `3 passed`; `git diff --check` reported no errors.
- Bumped scan cache version to v25 because old raw `db_invocations` do not contain the source-wrapper binding and semantics facts required by this contract.
- Code-review follow-up (spec axis, 2 findings fixed):
  - P1: a single signature-less external contract method entry no longer bypasses overload matching. `_wrapper_contract_method()` previously accepted the lone contract candidate unconditionally whenever it had no arity/parameter-type facts, even when the raw call site's own facts (`wrapper_method_arity`/`wrapper_parameter_types`) revealed a specific overload the contract entry could not confirm. It now only auto-accepts a signature-less lone candidate when the observed call site *also* has no distinguishing signature facts; otherwise it returns `ambiguous_overload` and the invocation stays `unresolved`.
  - P2: ambiguous/unavailable source overload candidates no longer collapse into opaque identity strings. `StaticAnalyzerHost` (`CreateAmbiguousInvocation`/`CreateUnavailableSourceCandidate`) now emits a structured `WrapperOverloadCandidateFact` (bound implementation identity, receiver type, method name, arity, parameter types, method identity) per candidate instead of a bare `MethodIdentity` string list. The Gateway (`_wrapper_candidate_fact`, new `overload_candidate_facts`/`wrapper_overload_candidate_facts` fields on `WrapperReconciliation`/`DbInvocation`) preserves these structured facts end-to-end alongside the existing identity-string `overload_candidates` field (kept for backward compatibility).
  - Regression tests added first (red before green): `test_external_contract_single_signatureless_method_stays_unresolved_against_specific_overload`, `test_ambiguous_source_overload_retains_structured_candidate_facts`, and `test_static_analyzer_host_ambiguous_overload_candidates_keep_structured_facts` (real built host); `test_static_analyzer_host_preserves_ambiguity_for_same_named_imports` updated since its raw-fact assertion shape changed from a set of strings to structured candidate dicts.
  - Bumped scan cache version to v26 since ambiguous/unavailable raw `wrapper_overload_candidates` are now structured facts, not opaque identity strings.
  - Validation: isolated `dotnet build tools\\StaticAnalyzerHost\\StaticAnalyzerHost.csproj --nologo` succeeded (0 warnings/errors); `tests/test_csharp_analysis_gateway.py` `106 passed`; combined focused suite (`test_csharp_analysis_gateway.py`, `test_execution_path_builder.py`, `test_execution_path_integration.py`, `test_program_refresh.py`, `test_sql_execution_graph.py`, `test_static_analyzer_host.py`) `170 passed`; VS Code diagnostics reported no errors.
