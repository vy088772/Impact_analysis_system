# 06 — Every program-name suffix copy strips all seven suffixes

**What to build:** A parity test feeds the seven program suffixes to every copy of the suffix rule. A review said two copies do not strip `.cshtml` and `.vue`. A first reading found both suffixes in every copy, so the report may be wrong. A green test closes the defect with a written finding. A red test gets a fix. After that, each repository keeps one definition of the rule. A copy that differs in logic, such as path handling, keeps its logic and calls the one suffix list. The work spans both repositories, which cannot share code.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] One shared case list of the seven suffixes runs against every copy in its repository. The canonical object identity mirror is the prior art.
- [ ] The result of the test is written in this ticket: green (false report) or red (which copy, which suffix).
- [ ] Each repository ends with one definition of the suffix list.
- [ ] No copy changes its behavior for a name that already worked.
- [ ] The two repositories land in separate commits.
