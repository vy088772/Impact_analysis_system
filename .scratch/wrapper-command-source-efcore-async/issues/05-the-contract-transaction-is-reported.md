# 05 — A Contract Transaction is reported, and a skipped one names why

**What to build:** A refresh that commits a Contract Transaction says so on the
operator's screen. A refresh that skips one names the gate that stopped it.

The automatic write path is already complete and already tested end to end. A
full refresh decompiles an external wrapper, stages a contract proposal, and
commits the external wrapper registry and the system catalog as one recoverable
unit. `refresh_source` returns that outcome. The `/refresh` response model does
not declare the field, so the API drops it silently, and `refresh_cli` never
prints it. An operator cannot tell a committed transaction from a skipped one.
The path looks absent only because its result never reaches the screen.

The skip reason is worse than absent. The outcome defaults to `not_required`
whenever any gate fails. Today's real IQCS state is "required, but preflight
failed", and the operator reads `not_required` — the literal opposite. This is
the failure mode the wrapper review rules already forbid: two different facts
read from one bucket.

The printed line carries the status and the contract names only. The transaction
identifier and the changed file paths already live in the manifest the Contract
Transaction writes. Printing them on every refresh would crowd out the wrapper
review rows an operator actually reads.

This ticket is sequenced first because it makes every later ticket's outcome
visible. It gates none of them: their acceptance is assertable on the returned
value alone.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] The `/refresh` response carries the Contract Transaction outcome as a declared, typed field — a later rename fails a test rather than silently emptying the line
- [x] `refresh_cli` prints one line for the Contract Transaction, carrying the status and the contract names
- [x] A refresh that commits prints a committed status naming the contracts it wrote
- [x] A refresh skipped because Contract Preflight failed reports `preflight_failed`, not `not_required`
- [x] A refresh skipped because it was scoped to named programs reports `program_scope`
- [x] A refresh skipped because no system identifier was given reports `no_system_id`
- [x] A refresh where no Contract needed committing still reports `not_required`, so the word keeps its literal meaning
- [x] A refresh that reaches no external wrapper at all prints no Contract Transaction line, so an unrelated refresh gains no noise

**Note:** `service/schemas.py` adds `ContractTransactionStatus` (a `Literal` of
the seven real outcomes) and `ContractTransactionSummary` (typed, `extra="allow"`
for `transaction_id`/`manifest_path`/`error_code`/`error`), and declares it as
`RefreshResponse.contract_transaction`. `service/analyze_service.py`'s
`refresh_source` now names the gate that stopped the commit — `program_scope`
(checked first: a partial refresh never commits), `no_system_id`, then
`preflight_failed` — before falling through to the commit attempt or the
literal `not_required`; a new `_selector_names()` helper turns the committed
selector into the `contracts` list. `llamaindex-spec-rag/impact_orch/refresh_cli.py`
adds `_print_contract_transaction()`, called from `main()` after the wrapper
summary; it prints `contract transaction: status=<status> contracts=<names or
<none>>`, gated on `wrapper_summary.totals.external_wrappers` so a refresh that
never reaches an external wrapper prints nothing.

Tests: `Impact_analysis_system/tests/test_refresh_atomic_commit.py` (two
existing assertions renamed from `not_required` to `program_scope`/
`no_system_id`, plus new `preflight_failed` and literal-`not_required` cases),
`tests/test_schemas.py` (typed-field + status-enum regression tests), and
`llamaindex-spec-rag/tests/test_refresh_cli.py` (printed line, per-status text,
and the no-external-wrapper suppression). `docs/openapi/openapi.json`
regenerated via `python -m tools.export_openapi_schema` so the schema fixtures
the CLI tests validate against stay current.

Full suite run: `Impact_analysis_system` — 890 passed, 12 failed, 1 skipped;
every failure was confirmed pre-existing against the parent commit (Windows
path/line-ending formatting and a Web.config fixture issue, none touching
`contract_transaction`, `refresh_source`, or `refresh_cli`). `llamaindex-spec-rag/tests/test_refresh_cli.py`
— 23 passed.
