# 05 — Schema-fixture validation test helper

**What to build:** A shared test helper in `impact_orch`'s test suite loads the exported OpenAPI schema (ticket 03) and validates a fixture dict against a named response shape from it. This is a prefactor: it exists so the test files migrated in tickets 06 and 07 don't each duplicate schema-loading and validation logic.

**Blocked by:** 03 — needs the exported schema file to load.

**Status:** done

- [x] A test helper/fixture loads the exported OpenAPI schema from its committed path
- [x] The helper validates a given fixture dict against a named response shape (e.g. `/refresh`'s `wrapper_summary`, `/path_evidence`'s response) and raises a clear failure when it doesn't match
- [x] The helper is written once and is directly reusable from any test file, with no per-file duplication
- [x] At least one test demonstrates the helper correctly rejects a fixture that doesn't match the schema

`llamaindex-spec-rag/tests/_schema_fixtures.py` created, with `tests/test_schema_fixtures.py` (7 tests, all passing). `SCHEMA_PATH` points at the sibling checkout's committed export (`_PROJECT_ROOT.parent / "Impact_analysis_system" / "docs" / "openapi" / "openapi.json"`, the same sibling-repo layout `impact_orch/output_writer.py` already assumes) and is loaded once via `lru_cache`. `assert_matches_schema(fixture, shape_name)` resolves `shape_name` as a `components/schemas` component (e.g. `"WrapperSummary"`, `"PathEvidenceResponse"`) and validates against it with `jsonschema`'s `Draft202012Validator`, wiring `$ref` resolution through a `referencing.Registry` (not the deprecated `RefResolver`, confirmed warning-free under `-W error::DeprecationWarning`). An unknown `shape_name` raises `UnknownResponseShapeError` (overriding `__str__` so the message isn't `repr()`-mangled by `KeyError`'s default formatting) listing the known shapes; a mismatched fixture raises `AssertionError` listing every validation error. Neither `jsonschema` nor `referencing` is pinned directly in `requirements.txt` — both are transitive dependencies of the already-pinned `chromadb`, documented as such in the module docstring. Reviewed via `/code-review`; both findings (the `KeyError.__str__` message-mangling bug, and the undocumented `referencing` dependency) were fixed.
