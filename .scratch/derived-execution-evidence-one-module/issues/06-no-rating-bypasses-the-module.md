# 06 — No rating bypasses the module, and the benchmark result does not change

**What to build:** Every endpoint gets Derived Execution Evidence only through the module. The retention bound comment states why the bound stays at 100. The Impact benchmark suite gives the same result as the baseline from ticket 01. See the spec, sections "Retention bound" and "Testing Decisions".

**Blocked by:** 03 — `/analyze` gets its evidence from the module; 04 — `/flow_chain` backward reuses the scope evidence; 05 — `/flow_chain` forward finds an MVC screen.

**Status:** resolved (2026-10-02). The baseline collection errors remain; see the note below.

- [x] No code outside the module calls the rating step or the path builder for Derived Execution Evidence.
- [x] The rating step is private to the module.
- [x] The retention bound stays at 100. Its comment states that only full derivations enter the retention, and that they come from the same scopes as before.
- [x] The eviction message stays.
- [x] The Impact benchmark suite gives the same result as the baseline. The three path-dependent ids are not a regression.
- [ ] The full test suite passes.

## Comments

### Completion note (2026-10-02)

**Affected function.** `evidence_for_scope` now calls the private rating step in its own module.
The rating step and its SQL, connection, method-chain, and source helpers moved from `analyze_service`.
The module no longer imports `analyze_service`, so the import cycle is gone.
The analysis service retains helper import names for its existing readers and tests.
No external code calls the rating step.
The endpoints supply module-built paths to the flow builders; their standalone fallbacks remain available.

**User-visible change.** This ticket changes no answer or response shape.
The retention bound remains 100, and its settings comment records why the scope count does not grow.
The eviction message is unchanged.
The MVC forward-chain change belongs to ticket 05, not this ticket.

**Tests.** Three old test groups now inject fixed evidence through the endpoint interface.
They no longer call or replace the private rating step.
The module, path, refresh, and SQL-cache checks give 167 passed.
The likely-match and inline-view checks give 22 passed.
The analyze and MVC forward-chain checks also passed during the change.

**Baseline comparison.** `final-pytest.txt` records the final run in the main checkout.
The command matches ticket 01:
`.venv/bin/python -m pytest -q -p no:cacheprovider --continue-on-collection-errors -rfE`.
The baseline gives 1592 passed, 41 warnings, and 2 collection errors.
The final run gives 1627 passed, 41 warnings, and the same 2 collection errors.
The earlier tickets added the tests; this ticket adds no test case.
There are no failed test cases and no path-dependent failures in this checkout.

**Full-suite limitation.** The last checklist item remains open because collection still fails in
`tests/test_search_roles.py` and `tests/test_sp_tables.py` with `KeyError: 'PUR'`.
Both tests need the unavailable `ODBC Driver 17 for SQL Server` and a live Database connection.
These errors are present in ticket 01's baseline and are not a regression.
Run the same command in an environment with that driver and connection to close this last item.

**Typecheck.** Scoped mypy reports 32 errors before and 27 after the change.
The moved helpers no longer contribute five existing errors.
The evidence module has no mypy error; the remaining errors are in unchanged analysis-service code.
The editor reports no errors in the changed product files.

**Code review.** The user selected `7aaac10` as the fixed point.
The read-only Standards and Spec agents each report zero findings.
The review used the uncommitted diff against that fixed point before the final commit.
