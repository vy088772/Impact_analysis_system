# 03 — Export the OpenAPI schema

**What to build:** This service's OpenAPI schema, covering at minimum the `/analyze`, `/refresh`, and `/path_evidence` response models, is exported to a versioned file committed in the repo. A small script regenerates the export from the live FastAPI app — it is never hand-maintained, so it can't silently drift from the real route definitions.

**Blocked by:** 01 — the export must reflect the newly-typed `wrapper_summary` shape, not the old untyped one.

**Status:** done

- [x] A script regenerates the exported schema file from the live FastAPI app
- [x] The exported file is committed to the repo at a stable, versioned path
- [x] The export covers `/analyze`, `/refresh`, and `/path_evidence` response models
- [x] The exported `/refresh` shape reflects the Pydantic model from ticket 01, not the old untyped dict

`tools/export_openapi_schema.py` regenerates `docs/openapi/openapi.json` from the live `service.api:app` (`app.openapi()`), serialized deterministically (`sort_keys=True`) so regenerating is a no-op diff when nothing changed. `--check` compares the live schema against the committed file without writing, for drift detection. `tests/test_export_openapi_schema.py` guards against drift (committed file must match a fresh regeneration) and asserts `/analyze`, `/refresh`, `/path_evidence` are present with response schemas, and that `/refresh`'s `wrapper_summary` is a `$ref` to the named `WrapperSummary` model (ticket 01's typed shape), not a bare object.
