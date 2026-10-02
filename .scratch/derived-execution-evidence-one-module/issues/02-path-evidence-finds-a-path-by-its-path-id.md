# 02 — `/path_evidence` gets its evidence from the module and finds a path by its path_id

**What to build:** `/path_evidence` asks the module for evidence and finds the requested Execution Path through a path_id index. It does not rebuild paths one invocation at a time. A request with program names gives the module its needed files. On a miss, the module rates those files only and retains nothing. A new ADR-0040 records this partial-rating exception. See the spec, sections "Cache behaviour", "Paths and the disk format", and "Decision record".

**Blocked by:** 01 — Derived Execution Evidence moves into its own module.

**Status:** ready-for-agent

- [ ] The entry point takes an optional list of needed files.
- [ ] A miss with no needed files runs a full derivation and retains it in memory and on disk.
- [ ] A miss with needed files rates those files only. The module writes nothing to memory or to disk.
- [ ] The evidence keeps the Execution Paths per invocation. It gives the paths of a given list of invocations, built on first use.
- [ ] The evidence finds one path by path_id, together with its invocation, or gives nothing.
- [ ] The disk store format version increases by one. A module-seam test shows that a file of the old version counts as a miss.
- [ ] A module-seam test shows that a partial miss leaves the retention and the disk folder empty.
- [ ] `/path_evidence` takes an optional evidence source. Endpoint-seam tests cover a found path, a missing path, and program ownership on an MVC screen.
- [ ] Without program names, `/path_evidence` asks for the whole scope.
- [ ] `/path_evidence` gives the same response as before for the present test cases.
- [ ] ADR-0040 states that the freshness rule does not change. It states that only the miss behaviour of a request with needed files differs from ADR-0013.
