# 05 — `/flow_chain` forward finds an MVC screen

**What to build:** `/flow_chain` in the forward direction resolves the program name through the same Program Screen resolution as `/analyze`. It applies action ownership. An MVC screen such as RTTalentDB `JobDutyMtn` then gets a forward chain. A reading of the code found this defect, so the work starts with a test that proves it. See the spec, sections "Endpoints" and "Testing Decisions".

**Blocked by:** 02 — `/path_evidence` gets its evidence from the module and finds a path by its path_id.

**Status:** ready-for-agent

- [ ] First, an endpoint-seam test on the `JobDutyMtn` Program Screen fixture expects a forward chain. It fails before the fix. If it passes, stop and report.
- [ ] Forward uses the same program resolution helper as `/analyze`.
- [ ] When one name resolves to several screens, forward merges their files and actions and builds one chain.
- [ ] When the anchor method is not an owned action, forward returns no chain.
- [ ] Forward gives the module the files of the resolutions as the needed files.
- [ ] The response shape does not change.
- [ ] A WebForms program gives the same forward chain as before.
- [ ] After the fix, one run against the real RTTalentDB returns a forward chain for `JobDutyMtn`. Record the result in this ticket under Comments.
