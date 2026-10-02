# 04 — `/flow_chain` backward reuses the scope evidence

**What to build:** `/flow_chain` in the backward direction asks the module for the evidence of the whole scope. A second backward request on one scope does not rate again. A backward request after `/find_by_table` on one scope does not rate again. The chains do not change. See the spec, section "Endpoints".

**Blocked by:** 02 — `/path_evidence` gets its evidence from the module and finds a path by its path_id.

**Status:** ready-for-agent

- [ ] The backward direction calls the entry point with no needed files.
- [ ] The backward direction uses the paths of the evidence and does not build paths again.
- [ ] `/flow_chain` takes an optional evidence source.
- [ ] An endpoint-seam test gives fixed evidence and checks the backward chains and the diagnostics.
- [ ] The present backward tests pass with no change in expected answers.
