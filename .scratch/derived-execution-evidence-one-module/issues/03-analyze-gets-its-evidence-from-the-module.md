# 03 — `/analyze` gets its evidence from the module

**What to build:** `/analyze` asks the module for evidence one time per request. It gives the files of all its resolutions and of their shared components as the needed files. It filters each resolution and each shared component from that one result. A warm scope answers fast. A cold scope answers as fast as today. The answers do not change. See the spec, sections "Read-only evidence" and "Endpoints".

**Blocked by:** 02 — `/path_evidence` gets its evidence from the module and finds a path by its path_id.

**Status:** ready-for-agent

- [ ] One `/analyze` request calls the entry point one time.
- [ ] The needed files include the files of every shared component.
- [ ] `/analyze` filters invocations first, then asks for their paths.
- [ ] The branch without a SQL graph and without a Database copies each path before it rewrites the unresolved reason.
- [ ] An endpoint-seam test runs `/analyze` two times on one retained evidence. The retained paths do not change.
- [ ] `/analyze` takes an optional evidence source. Endpoint-seam tests cover a WebForms program, an MVC Program Screen, and a shared component.
- [ ] The present `/analyze` tests pass with no change in expected answers.
