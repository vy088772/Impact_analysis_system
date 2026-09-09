# 01 — Server address normalization strips a protocol prefix and a port

**What to build:** A connection string that names its server as `tcp:host.example.net,1433` reaches
the same SQL Cache Identity as one that names it `host.example.net`. Today the
protocol prefix and the port suffix survive normalization, so one host can hold
two identities and a cache written under one is invisible to the other. This
contradicts ADR-0009, which states that one host never holds two identities.

The Azure SQL connection in the EnterpriseApi repository is written in exactly
this shape. WebForms Systems benefit from the same repair, because the rule is
shared.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] A server written with a `tcp:` protocol prefix normalizes to the same value as the same server written without it.
- [x] A server written with a `,port` suffix normalizes to the same value as the same server written without it.
- [x] A server written with both normalizes to the same value as one written with neither.
- [x] The existing rules are unchanged: a named-instance suffix is still dropped, a host with no dot still gains the internal domain, and the result is still lowercased.
- [x] An empty server still yields an empty result, and the caller still decides whether that is an error.
- [x] A host that already carries a dot still does not gain the internal domain, so an external host name is never rewritten into an internal one.

## Note

Change is in `normalize_server()` in `service/sql_cache_store.py`. The function
now strips a `tcp:` prefix, then a `,port` suffix, then the named-instance
suffix, in that order. The order handles a port after a named instance too
(`host\instance,1433`), because the port strip runs first and leaves the
instance suffix for the next step.

Tests added in `tests/test_sql_cache_store.py`:
- `test_tcp_protocol_prefix_is_discarded`
- `test_port_suffix_is_discarded`
- `test_protocol_prefix_and_port_suffix_together_normalize_like_neither`
- `test_port_suffix_is_discarded_before_the_domain_suffix_is_added`
- `test_port_suffix_with_named_instance_suffix_is_discarded`

Verification: `pytest tests/test_sql_cache_store.py` passes (62 tests). The full
suite (`pytest`) has 12 pre-existing failures unrelated to this change
(Windows CRLF line-ending mismatch, missing web.config test fixtures, and
wrapper-contract state issues) — none touch `sql_cache_store.py` or
`normalize_server`.
