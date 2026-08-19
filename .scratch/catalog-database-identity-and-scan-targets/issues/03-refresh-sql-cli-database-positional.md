# 03 — The SQL Scan Command Takes a Database Positionally

**What to build:** An operator scans a Database by typing its name, and the word they type has exactly one meaning. The SQL scan command's positional argument becomes one or more Database names; the System convenience mode moves to an explicit, repeatable flag. A positional name is resolved against the Database Registry, and how many servers register it decides what happens: none refuses with the direct-targeting form to use instead, one scans it, several refuses listing every candidate. This is also what makes the hint from ticket 07 a command that actually runs.

**Blocked by:** 01 — the System mode must already resolve from complete Declared Database Dependencies before its command-line shape moves.

**Status:** done

- [x] The positional argument accepts one or more Database names. Passing several scans each in turn.
- [x] The System mode moves to a repeatable `--system_id` flag, matching how the source-refresh command's existing per-program flag repeats.
- [x] Positional Database names combined with `--system_id` in one invocation are rejected, extending the existing prohibition on combining direct server/database targeting with a System argument.
- [x] Direct `--server`/`--database` targeting and the schema flag behave exactly as they do today, including still bypassing the catalog entirely.
- [x] `<scan command> STC` unambiguously means the Database named `STC`, never the System named `STC`.
- [x] A registry query returns **every** server registering a given Database name. It never raises, never chooses, and never consults the System catalog. Server addresses are normalized through the existing cache-identity rule first, so short hostnames and named-instance forms match the same registered server.
- [x] A positional name registered on exactly one server is scanned with no interaction.
- [x] A positional name registered on no server is refused with an error that names the Database and gives the complete direct-targeting command to use instead. Nothing is written to the Database Registry — scanning an unregistered Database never registers it as a side effect.
- [x] A positional name registered on several servers is refused with an error listing every candidate and naming the direct-targeting flag as the way through. This is the final behaviour for a run with no terminal attached, not a placeholder; ticket 04 adds the interactive path above it.
- [x] Command help text and the worked examples in the affected command docstrings are updated to the new shape.
- [x] The existing tests that pass a System identifier positionally are updated to the new flag rather than deleted.
- [x] Tests cover: one server scans directly; zero servers refuses with the direct-targeting form; several servers refuses listing candidates; `--system_id` expanding every declared dependency; mixing the two forms rejected; and direct targeting still never touching the catalog, guarded by the suite's existing "touching the catalog fails the test" helper.
