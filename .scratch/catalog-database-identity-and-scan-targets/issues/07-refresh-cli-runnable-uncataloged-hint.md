# 07 — The Uncataloged-Database Hint Names Its Server and Actually Runs

**What to build:** An analyst who copies the hint the source-refresh command prints runs the right command, on the right host, without going hunting for which server the Database is on. The hint becomes a directly runnable direct-targeting scan command with both values filled in, plus a follow-up line about registering the Database afterwards. Two same-named Databases on different servers stop being reported as one line with their counts added together.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Each Uncataloged Database in the source-refresh command's unresolved summary prints a directly runnable scan command using direct server/database targeting, with both values filled in.
- [ ] A second line instructs the operator to register that Database under that server afterwards, keeping the scan and the cataloging visible as separate steps.
- [ ] Uncataloged results are aggregated by the `(server, database)` pair. Two Databases sharing a name on different servers report as two lines with their own call counts, never as one line with the counts summed.
- [ ] Each distinct pair prints once regardless of how many invocations hit it, preserving today's deduplication behaviour.
- [ ] The server value is read from the field the refresh response already carries on its wrapper observations. **This ticket requires no change to the analysis service** — the caller reads a field it was already being sent.
- [ ] The source-refresh command still writes to neither catalog file and still triggers no live scan. The hint remains a suggestion a human acts on.
- [ ] The existing assertions on the hint text are updated to the new wording rather than deleted.
- [ ] Tests cover: the two-line hint with server and database filled in; two same-named Databases on different servers reported as separate lines with separate counts; and one entry per pair regardless of how many invocations hit it.
