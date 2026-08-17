# 06 — Wire rag_client and migrate context_builder / path_selection

**What to build:** `rag_client.py`'s `analyze()` and `path_evidence()` call the new `evidence_status` module at their existing return points, so they return already-typed evidence values instead of raw JSON. `context_builder.py` and `path_selection.py` — the two real consumers of that data — switch to reading evidence exclusively through these typed values, replacing their current ad hoc, inconsistent dict-reading. Because `rag_client.py`'s return shape changes, these two consumers must migrate in the same ticket — landing the seam without its consumers (or vice versa) leaves the code broken, not just incomplete.

**Blocked by:** 04 (the module must exist), 05 (fixture rewrite needs the validation helper).

**Status:** ready-for-agent

- [ ] `rag_client.py`'s `analyze()` and `path_evidence()` return typed evidence values via the `evidence_status` module instead of raw JSON
- [ ] `rag_client.py`'s other five HTTP functions (`refresh`, `find_by_sp`, `find_by_table`, `flow_chain`) are unmodified
- [ ] `context_builder.py` reads evidence data exclusively through the new typed values; its previous ad hoc `evidence`/`evidence_status` dict-reading is removed
- [ ] `path_selection.py` reads evidence data exclusively through the new typed values; its previous ad hoc `evidence`/`evidence_status` dict-reading is removed
- [ ] `tests/test_path_selection.py` and `tests/test_path_evidence_wiring.py` fixtures are rewritten using the schema-validation helper (ticket 05) instead of hand-written dicts
- [ ] Existing assertions on rendered output pass unchanged — this is a parsing-path change, not a behavior change
