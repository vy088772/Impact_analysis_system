# 04 — Choose Between Servers When a Database Name Is Ambiguous

**What to build:** An operator who types a Database name registered on several servers is shown the candidates and picks one, instead of being turned away. Each candidate shows its server, database, and when it was last scanned, so the servers can be told apart by something more useful than their names. A run with no terminal attached keeps failing immediately rather than blocking on input that will never arrive.

**Blocked by:** 02 (the last-scan-time column reads Scan Records through the listing), 03 (the ambiguous-name case and its candidate list must exist first).

**Status:** ready-for-agent

- [ ] With a terminal attached, a positional Database name registered on several servers presents the candidates and scans the one the operator chooses.
- [ ] Each candidate row shows server, database, and last scan time.
- [ ] Candidates are ordered by server, then database. The ordering key is independent of scan state, so a given server holds the same position across runs and a choice cannot silently shift because something was scanned since the last run.
- [ ] A candidate with no Scan Record displays as never scanned rather than blank, and its position in the ordering is unaffected by that.
- [ ] With no terminal attached, resolution refuses immediately — listing every candidate and naming the direct-targeting flag — exactly as ticket 03 left it. It never prompts, and never blocks waiting for input.
- [ ] The Scan Record listing is fetched only when a choice actually has to be presented, never on the unambiguous paths.
- [ ] The interaction point is injected into the existing target-resolution entry point as a callable defaulting to the real terminal prompt. No new module is introduced for it, and tests reach it through that existing entry point rather than by patching input primitives.
- [ ] Tests cover: several candidates with a chooser present returning the chosen target; several candidates with no terminal refusing; ordering by server then database; a never-scanned candidate displayed as such and not reordered; and the listing not being fetched when only one server matches.
