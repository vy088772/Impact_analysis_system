# 04 — Build the evidence_status module

**What to build:** In `llamaindex-spec-rag`'s `impact_orch` package, one new module owns interpreting this service's Evidence Status data. It exposes exactly three functions: an accessor parsing a Database Invocation's own evidence rating into a typed value, a separately-named accessor parsing a wrapper-evidence-bag's evidence status into its own typed value (including the `not_applicable` sentinel), and a boolean helper reporting whether a given typed value counts as verified (`proven`/`likely`) versus unresolved. The two accessors return genuinely separate types so a caller cannot accidentally pass one concept's raw data to the other's accessor. This ticket only builds and unit-tests the module — it is not wired into any existing call site yet.

**Blocked by:** 01 — the module is built against this service's now-typed `/refresh` contract, not guessed ahead of it.

**Status:** ready-for-agent

- [ ] One accessor parses a Database Invocation's own evidence rating from raw response data into a typed value
- [ ] A separately-named, separately-typed accessor parses a wrapper-evidence-bag's evidence status from raw response data, including `not_applicable`
- [ ] A boolean helper takes either typed value and reports verified vs. unresolved
- [ ] Unit tests cover all four known values for each accessor
- [ ] A unit test confirms an unrecognized/future value fails loudly rather than silently defaulting
- [ ] No existing call site (`context_builder.py`, `path_selection.py`, `refresh_cli.py`, `rag_client.py`) is modified by this ticket
