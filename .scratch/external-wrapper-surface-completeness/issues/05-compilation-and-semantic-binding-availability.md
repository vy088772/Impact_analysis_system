# 05 — Build a compilation per project and report Semantic Binding Availability

**What to build:** A maintainer can see whether the analyzer had a semantic model for each scanned project. The analyzer builds a compilation from the project's own declarations, and it reports the result of that attempt. Classification results do not change yet.

The analysis host performs no semantic analysis today. It builds no compilation, and it uses no semantic model. It reads syntax trees alone. This ticket adds the compilation and the reporting, and nothing else. It is the tracer bullet for the next ticket.

Introduce **Semantic Binding Availability** as the named state of the semantic model for one scanned project. It holds one of three values: `available`, `unavailable_no_project_file`, or `unavailable_reference_resolution_failed`.

A degraded analysis must never look like a confident analysis. Report the state, and never fall back in silence.

**Blocked by:** 04 — the contract side must be correct and verified before the call-site side changes, so that a later result difference has one cause and not two.

**Status:** ready-for-agent

- [ ] The analyzer builds one compilation for each project file found under a scan root.
- [ ] The compilation takes its source file list and its reference list from the project file.
- [ ] A framework reference resolves against the .NET Framework reference assembly package.
- [ ] An external assembly reference resolves against the project output directory.
- [ ] A scan root that holds no project file yields the state `unavailable_no_project_file`, and the analyzer uses the syntax-only path.
- [ ] A reference that fails to resolve yields the state `unavailable_reference_resolution_failed`, and the analyzer uses the syntax-only path.
- [ ] The refresh output reports the Semantic Binding Availability for each scanned project.
- [ ] Every classification result stays identical to the result before this ticket.
- [ ] The analyzer builds one compilation for each project, and not one for each file.
- [ ] A test asserts that a scan root without a project file reports `unavailable_no_project_file`.
