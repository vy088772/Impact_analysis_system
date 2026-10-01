# 06 — Every program-name suffix copy strips all seven suffixes

**What to build:** A parity test feeds the seven program suffixes to every copy of the suffix rule. A review said two copies do not strip `.cshtml` and `.vue`. A first reading found both suffixes in every copy, so the report may be wrong. A green test closes the defect with a written finding. A red test gets a fix. After that, each repository keeps one definition of the rule. A copy that differs in logic, such as path handling, keeps its logic and calls the one suffix list. The work spans both repositories, which cannot share code.

**Blocked by:** None — can start immediately.

**Status:** done (branches `ticket06-suffix-server` and `ticket06-suffix-client`, not merged)

- [x] One shared case list of the seven suffixes runs against every copy in its repository. The canonical object identity mirror is the prior art.
- [x] The result of the test is written in this ticket: green (false report) or red (which copy, which suffix).
- [x] Each repository ends with one definition of the suffix list.
- [x] No copy changes its behavior for a name that already worked.
- [x] The two repositories land in separate commits.

## Finding

The review was **right for the client** and **wrong for the server**.

- **Case list:** the `program_suffixes` list in `tests/cross_repository_agreement.json` (server repository). It holds the seven suffixes, one upper-case name, and one name with no suffix. Both repositories read it.
- **Server: green.** `analyze_service._normalize_program` strips all seven suffixes. The service has one definition, `_KNOWN_SUFFIXES`. `flow_chain_builder._paired_view_file_names` handles only the two WebForms code-behind suffixes by design. It is not a program-name strip, so it stays.
- **Client: red for two copies.** `impact_orch.agent_tools._program_key` and `impact_orch.context_builder._program_key` kept `.cshtml` and `.vue` (`order.cshtml` instead of `order`). The other three copies passed: `revision_query.strip_known_program_suffix`, `grounding._norm`, `routing_expectations._program_object_key`.
- **Fix:** the client writes the list once, as `query.revision_query.KNOWN_PROGRAM_SUFFIXES`. `grounding` and `routing_expectations` keep their own logic (code-extension check, path handling) and read that list. The two `_program_key` functions call `strip_known_program_suffix`. Their old five-suffix names stay stripped the same way.
- **Test run:** the client suite shows 1286 passed and 3 failed. The 3 failures are `test_table_lookup_write_access_types.py` (ticket 07). They need the sibling checkout at its normal path.
