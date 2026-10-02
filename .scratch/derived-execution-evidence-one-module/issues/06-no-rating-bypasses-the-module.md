# 06 — No rating bypasses the module, and the benchmark result does not change

**What to build:** Every endpoint gets Derived Execution Evidence only through the module. The retention bound comment states why the bound stays at 100. The Impact benchmark suite gives the same result as the baseline from ticket 01. See the spec, sections "Retention bound" and "Testing Decisions".

**Blocked by:** 03 — `/analyze` gets its evidence from the module; 04 — `/flow_chain` backward reuses the scope evidence; 05 — `/flow_chain` forward finds an MVC screen.

**Status:** ready-for-agent

- [ ] No code outside the module calls the rating step or the path builder for Derived Execution Evidence.
- [ ] The rating step is private to the module.
- [ ] The retention bound stays at 100. Its comment states that only full derivations enter the retention, and that they come from the same scopes as before.
- [ ] The eviction message stays.
- [ ] The Impact benchmark suite gives the same result as the baseline. The three path-dependent ids are not a regression.
- [ ] The full test suite passes.
