# 03 — Export the OpenAPI schema

**What to build:** This service's OpenAPI schema, covering at minimum the `/analyze`, `/refresh`, and `/path_evidence` response models, is exported to a versioned file committed in the repo. A small script regenerates the export from the live FastAPI app — it is never hand-maintained, so it can't silently drift from the real route definitions.

**Blocked by:** 01 — the export must reflect the newly-typed `wrapper_summary` shape, not the old untyped one.

**Status:** ready-for-agent

- [ ] A script regenerates the exported schema file from the live FastAPI app
- [ ] The exported file is committed to the repo at a stable, versioned path
- [ ] The export covers `/analyze`, `/refresh`, and `/path_evidence` response models
- [ ] The exported `/refresh` shape reflects the Pydantic model from ticket 01, not the old untyped dict
