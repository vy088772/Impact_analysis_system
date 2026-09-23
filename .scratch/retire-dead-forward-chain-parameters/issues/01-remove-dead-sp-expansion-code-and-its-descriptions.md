# 01 — Remove the dead SP-expansion code and the descriptions of it

**What to build:** The code and the docs stop claiming that the forward chain expands nested SP calls recursively, or that it looks up SQL objects live on a cache miss. Delete the private SP-expansion function in `flow_chain_builder`, which has no caller. Delete the `sp_call_fetcher` module, whose only caller is that function. Correct every description of this behavior: the `flow_chain_builder` module docstring, the advanced manual's file tree, and the `view_fetcher` module docstring (see ADR-0011). The result of the forward chain does not change. See `../spec.md` for the reason behind each step.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `flow_chain_builder` no longer contains the SP-expansion function, its depth-cap constant, or the imports that only it used
- [ ] `flow_chain_builder` still imports every name that its remaining functions use
- [ ] The `sp_call_fetcher` module no longer exists
- [ ] The `flow_chain_builder` module docstring no longer says that the forward chain expands nested SP calls, and no longer names `sp_call_fetcher`
- [ ] The advanced manual's file tree no longer lists `sp_call_fetcher`
- [ ] The `view_fetcher` module docstring says that the module skips a name that the cache does not hold, and no longer mentions a live SQL Server lookup
- [ ] A repo-wide search (excluding `.scratch/`) finds no reference to `sp_call_fetcher` or to the deleted SP-expansion function
- [ ] No test file changed
- [ ] The full test suite has no new failure compared to the commit before this ticket

**Note:** the `.py` files in `service/` use CRLF line endings. Keep them.

## Comments
