# 05 — Schema-fixture validation test helper

**What to build:** A shared test helper in `impact_orch`'s test suite loads the exported OpenAPI schema (ticket 03) and validates a fixture dict against a named response shape from it. This is a prefactor: it exists so the test files migrated in tickets 06 and 07 don't each duplicate schema-loading and validation logic.

**Blocked by:** 03 — needs the exported schema file to load.

**Status:** ready-for-agent

- [ ] A test helper/fixture loads the exported OpenAPI schema from its committed path
- [ ] The helper validates a given fixture dict against a named response shape (e.g. `/refresh`'s `wrapper_summary`, `/path_evidence`'s response) and raises a clear failure when it doesn't match
- [ ] The helper is written once and is directly reusable from any test file, with no per-file duplication
- [ ] At least one test demonstrates the helper correctly rejects a fixture that doesn't match the schema
