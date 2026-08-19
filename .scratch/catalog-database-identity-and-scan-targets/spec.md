---
status: ready-for-agent
triage: ready-for-agent
---

# Give a System's Database Dependency a Complete Identity, and Make Scan Targets Explicit

## Problem Statement

`CONTEXT.md` defines a **Database** as "a physical SQL Server database identified by the pair (server, database name), independent of any System." `system_catalog.json` does not store that pair. A System's `databases` field is a list of bare name strings, so a System's dependency records only half a Database identity, and the missing half is guessed later.

The guess is currently silent. `resolve_db_server()` scans the server groups in `SQLServerData.json` and returns the **first** group whose `databases` list contains the requested name. With one registered server this happens to be right. The moment the same database name legitimately exists on two servers — `PUR` on both `vmsystest07` and `vmsystest08`, both of them real and both of them needed — several things break at once, and none of them announce themselves:

1. **A System's real dependency becomes unrepresentable.** The `STC` System depends on the `PUR` that lives on `vmsystest07`. There is nowhere in `system_catalog.json` to write "the one on `vmsystest07`". No downstream mechanism can recover that — a prompt would be asking the operator to re-supply a fact that is already fixed and already known, on every single run.
2. **`refresh_sql_cli --system_id STC` becomes permanently unusable.** Expanding that System's declared dependencies hits the ambiguous name every time, so the convenience mode fails on every invocation rather than in an edge case.
3. **Question answering silently analyzes the wrong database.** `resolve_db_source()` feeds `/analyze` and `/path_evidence` the SQL cache source for a System. Given an ambiguous name it returns the first-matched server without error, so the analysis runs against a real cache — just the wrong one. Nothing in the result says so.

Three further problems in the same area are already visible today, with one registered server:

4. **`refresh_sql_cli`'s positional argument is ambiguous and its published hint is not runnable.** The positional takes a `system_id`, but `STC` is simultaneously a `system_id` and a database name, so `refresh_sql_cli STC` has two plausible meanings. Meanwhile `refresh_cli`'s uncataloged-database hint prints ``refresh_sql_cli 建立 `SysErrorRecord` `` — and `SysErrorRecord` is a database name, not a `system_id`, so an operator who copies that hint runs the wrong command.
5. **The uncataloged-database hint omits the server and mis-aggregates.** The Web.config resolution already carries the resolved `server` alongside `database` all the way into the refresh response, but the hint prints only the database name, so the operator must go hunting for which host it is. Worse, the hint aggregates its call counts by database name alone — two different databases that happen to share a name on different servers are reported as one line with their counts added together.
6. **Nothing on the caller side can see when a database was last scanned.** A Scan Record lives only in `Impact_analysis_system`'s local cache directory. There is no endpoint that exposes them, and the two repos share no filesystem — they communicate only over HTTP. An operator deciding whether a database needs re-scanning has no way to ask.

Finally, a security-shaped problem that the codebase already contradicts itself about:

7. **Scan credentials sit in plaintext in the file most likely to be shared.** `SQLServerData.json` carries `uid`/`pwd` per server. It is `.gitignore`d, so version control is covered — but it is also the registry, which means it is exactly the file an operator copies to a colleague or attaches to a ticket when onboarding a new server. A registry wants to be circulated; a credential does not. The two uses are in direct tension in one file. `config.py`'s own comment beside that setting still reads "絕不存放任何帳號密碼（見 ADR-0001）", left behind by a mid-flight reversal, so the codebase currently carries both instructions at once.

## Solution

A System's declared dependency carries a **complete** Database identity. `system_catalog.json`'s `databases` becomes a list of `{server, name}` objects instead of bare name strings. "The `STC` System depends on the `PUR` on `vmsystest07`" becomes directly expressible, `--system_id` mode never needs to resolve a server, and the question-answering path can no longer resolve to the wrong database because it no longer resolves anything — it reads the pair it was given.

Resolving a bare database name stops being a library concern that guesses, and becomes a command-line concern that asks. `resolve_db_server()` — which returned one server and silently picked the first — is replaced by a plain query returning **every** registered server for a name. It never raises and never chooses. `refresh_sql_cli` is the single place that decides what to do with the answer: none found, scan directly; exactly one found, scan it; several found, present them and let the operator choose.

`refresh_sql_cli`'s command line is re-cut along the same line. Its positional argument becomes a **database name** — the thing an operator actually types when they want to scan a database — and the System convenience mode moves to an explicit `--system_id` flag. `refresh_cli`'s hint becomes a genuinely runnable command, complete with the server it already knows.

The Scan Record becomes readable without merging anything. The **Database Registry** keeps recording intent (which Databases exist, on which server, scanned under which identity); the **Scan Record** keeps recording fact (whether a scan actually happened, and when). A new read-only endpoint lets the caller ask Impact for the facts, so the two never need to be kept in sync and can never disagree.

Scan credentials move out of the registry without leaving it. The registry records the **name of the environment variable** holding each value; the values themselves live in `llamaindex-spec-rag`'s `.env`. A named variable that cannot be read is a hard error, never a silent fall back to the global identity — so a forgotten `.env` entry announces itself with the exact variable name instead of surfacing later as an unreadable SQL Server permission failure.

## User Stories

### A System's Database dependency

1. As a maintainer of `llamaindex-spec-rag`, I want each entry in a System's `databases` list to be a `{server, name}` object rather than a bare name string, so that a System's dependency records a complete Database identity as `CONTEXT.md` defines it, not half of one.
2. As a maintainer of `llamaindex-spec-rag`, I want to express that the `STC` System depends on the `PUR` on `vmsystest07` specifically, so that the same database name existing on a second server does not make my System's real dependency unrepresentable.
3. As an analyst running `refresh_sql_cli --system_id STC`, I want every declared dependency to expand to the exact server it names, so that the convenience mode keeps working after a second server registers a database with a colliding name.
4. As an analyst asking an impact-analysis question, I want the SQL cache source for a System to come from the complete pair its catalog entry declares, so that my answer can never be silently computed against a same-named database on the wrong server.
5. As an analyst asking an impact-analysis question, I want that path to require no server resolution at all, so that a registry ambiguity can never turn a question into an error in a flow where I have no way to resolve it.
6. As a maintainer of `llamaindex-spec-rag`, I want the four existing declared dependencies migrated in place to the new shape, so that the change lands without a re-scan and without re-deriving which server anything is on.
7. As a maintainer of `llamaindex-spec-rag`, I want a System with no declared dependency to keep an empty list, so that the "this System declares nothing" case reads the same as it does today.

### Looking up a bare database name

8. As a maintainer of `llamaindex-spec-rag`, I want the registry lookup for a bare database name to return every server that registers it, so that the caller sees the real answer instead of an arbitrary first match.
9. As a maintainer of `llamaindex-spec-rag`, I want that lookup to be a plain query that never raises and never chooses, so that deciding what to do about multiplicity belongs to the one caller that has an operator present.
10. As a maintainer of `llamaindex-spec-rag`, I want the lookup to keep normalizing server addresses under the existing cache-identity rule, so that a short hostname and a named-instance form still match the same registered server.

### `refresh_sql_cli`'s command line

11. As an analyst, I want `refresh_sql_cli <database name>` to mean "scan this database", so that the argument I type is the thing I am thinking about.
12. As an analyst, I want the System convenience mode behind an explicit `--system_id` flag, so that `refresh_sql_cli STC` has exactly one meaning even though `STC` is both a System and a database.
13. As an analyst, I want to pass several database names positionally in one invocation, so that scanning a handful of databases does not need one command each.
14. As an analyst, I want `--system_id` to be repeatable, so that I can refresh several Systems' dependencies in one invocation, matching how `refresh_cli`'s `--program` already works.
15. As an analyst, I want positional database names and `--system_id` to be rejected when mixed in one invocation, so that a command means one thing, matching the existing rule for `--server`/`--database` versus a System argument.
16. As an analyst, I want `--server`/`--database` to keep working exactly as it does today, so that a Database with no owning System stays scannable without inventing a fake System for it.
17. As an analyst copying the hint `refresh_cli` printed, I want it to be a command that actually runs, so that the suggested next step is not a dead end.

### Choosing between servers

18. As an analyst who typed a database name registered on exactly one server, I want the scan to start immediately, so that the common case costs no extra interaction.
19. As an analyst who typed a database name registered on several servers, I want the candidates listed with their server, database, and last scan time, so that I can tell the servers apart by something more useful than their names alone.
20. As an analyst reading that list, I want it ordered by server (then database), so that the same server sits at the same position on every run and my choice does not silently shift because someone else scanned something yesterday.
21. As an analyst reading that list, I want a candidate that has never been scanned to show that plainly rather than showing a blank, so that "never scanned" and "scan time unavailable" do not look alike.
22. As an operator running `refresh_sql_cli` from a script or scheduled job, I want an ambiguous name to fail loudly rather than wait on a prompt, so that a batch run can never hang on input that will never arrive.
23. As an operator whose scripted run just failed on an ambiguous name, I want the error to list every candidate and name `--server` as the way through, so that fixing the script does not require reading the source.
24. As an analyst who typed a database name that is registered nowhere, I want an error that hands me the `--server`/`--database` form with the name filled in, so that an unregistered database is still one command away from being scanned.
25. As a maintainer of `llamaindex-spec-rag`, I want scanning an unregistered database to never write it into the registry as a side effect, so that cataloging stays a deliberate, separately-authorized step and a scan command cannot quietly expand the registry.

### Validating declared dependencies

26. As an analyst running `refresh_sql_cli --system_id STC`, I want each declared `{server, name}` verified against the registry before any connection is attempted, so that a mistyped catalog entry cannot make the tool connect to a host nobody registered.
27. As an analyst hitting that validation, I want the error to name the System, the offending pair, and where to register it, so that I can fix it without tracing the lookup myself.
28. As an analyst asking an impact-analysis question, I want that validation *not* to run on the question-answering path, so that a catalog typo does not block questions that never open a connection.

### Seeing what has been scanned

29. As an analyst, I want a read-only endpoint that lists every SQL cache Impact holds with its server, database, schema, and scan time, so that the caller can report scan freshness without the two repos sharing a filesystem.
30. As a maintainer of both repos, I want a Scan Record to stay where the scanner writes it and never be copied into the Database Registry, so that "the registry claims it was scanned" can never disagree with what is actually on disk.
31. As an analyst, I want that listing to include caches for databases the registry does not list, so that a database scanned by direct `--server`/`--database` targeting stops being invisible.
32. As an analyst, I want a cache whose data file exists without readable metadata to still be listed, with its scan time reported as unknown, so that a partially-written cache is visible rather than absent.

### Scan credentials

33. As a maintainer of `llamaindex-spec-rag`, I want a server's optional scan-credential override recorded in the registry as the *names* of two environment variables rather than the values, so that the file I circulate when onboarding a new server carries no secret.
34. As a maintainer of `llamaindex-spec-rag`, I want the values themselves read from `llamaindex-spec-rag`'s `.env`, so that they live where this repo already keeps secrets and load through the mechanism already in place.
35. As a maintainer of `llamaindex-spec-rag`, I want a named variable that cannot be read to raise immediately, naming the variable, so that forgetting the `.env` entry is a three-second fix rather than an unreadable SQL Server permission error.
36. As a maintainer of `llamaindex-spec-rag`, I want a half-filled override — one variable named, the other blank — to raise rather than fall back, so that a partially-applied edit cannot silently scan under the wrong identity.
37. As a maintainer of `llamaindex-spec-rag`, I want both fields blank to keep meaning "use the global scan identity", so that the default path is unchanged and no server needs an override it does not want.
38. As a maintainer of `Impact_analysis_system`, I want the `/refresh_sql` request contract unchanged — the caller still sends the credential pair by value — so that moving where the caller reads them from requires no change on the Impact side and does not weaken the trust boundary.
39. As a maintainer of `llamaindex-spec-rag`, I want the stale "絕不存放任何帳號密碼" comment beside the registry setting rewritten to describe the rule that actually holds, so that the codebase stops carrying two contradictory instructions.

### Better hints from `refresh_cli`

40. As an analyst running `refresh_cli`, I want the uncataloged-database hint to include the server it already resolved, so that I do not have to work out which host the database is on.
41. As an analyst running `refresh_cli`, I want that hint printed as a directly runnable `--server`/`--database` command, so that the next step is copy-and-paste even though the database is not registered yet.
42. As an analyst running `refresh_cli`, I want a second line telling me to register the database afterwards, so that the scan and the cataloging are both visible as separate steps.
43. As an analyst running `refresh_cli`, I want uncataloged results aggregated by server *and* database, so that two same-named databases on different servers are reported as two lines rather than one line with their counts added together.
44. As a maintainer of `Impact_analysis_system`, I want this to require no change on the Impact side, so that a caller-side reporting improvement does not touch the analysis service.

### Recording the decisions

45. As a future maintainer, I want the reversal of "a System declares Databases as a list of names" recorded as a superseding decision rather than applied as a quiet format change, so that reading the original decision leads me to the one that replaced it.
46. As a future maintainer, I want the move of scan credentials out of the registry recorded as superseding the existing scan-identity decision, and noted in that decision's own repo, so that the two repos cannot drift into describing different rules.
47. As a future maintainer, I want the refusal to merge scan metadata into the registry recorded as a decision, so that "why are these two files not one?" has a written answer.
48. As a future maintainer, I want the inversion of `refresh_sql_cli`'s positional argument recorded as a decision, so that "why does the System need a flag when the database does not?" has a written answer.

## Implementation Decisions

### The Database dependency shape (`llamaindex-spec-rag`)

- `system_catalog.json`'s per-System `databases` field changes from a list of name strings to a list of `{server, name}` objects. Both keys are required on every entry; a System that declares no dependency keeps an empty list.
- `databases` is hand-maintained — the catalog builder does not read, write, or preserve it, and needs no change. Migration is a direct edit of the four existing entries (three on the `STC` System, one on `Y-Docs_TTPUR`), all of which target the single currently-registered server.
- `source_resolver.resolve_databases()` returns the list of `{server, name}` pairs as declared. `resolve_db_source()` returns the first declared pair directly and performs no registry lookup. Taking the first entry as "this System's own SQL cache source" is unchanged from today and remains a known simplification — no `primary`/`owned` marker is introduced.
- `resolve_db_server(name) -> str` is replaced by a query returning **all** registered servers for a name as a list. It never raises, never picks, and never consults the System catalog. Server addresses are normalized through the existing cache-identity rule before comparison, so short hostnames and named-instance forms match the same registered server.
- The **Database Registry** stays in `llamaindex-spec-rag`, stays the sole registry of which Databases exist on which server, and is still consulted on every scan — now for credential resolution and dependency validation rather than for server lookup. It is not read by `Impact_analysis_system`.

### `refresh_sql_cli`'s command line (`llamaindex-spec-rag`)

- The positional argument becomes one or more **database names**. The System convenience mode moves to a repeatable `--system_id` flag. Positional names and `--system_id` may not be combined in one invocation; the existing prohibition on combining `--server`/`--database` with a System argument extends to the new flag. `--server`/`--database` and `--schema` are otherwise unchanged.
- A positional database name is resolved against the registry, and the count of matching servers decides the outcome:
  - **zero** — a `TargetResolutionError` naming the database and giving the `--server`/`--database` form to use instead. Nothing is written to the registry; scanning an unregistered database never catalogs it as a side effect.
  - **one** — that target is scanned, with no interaction.
  - **more than one** — the operator chooses, subject to the interaction rules below.
- Candidate presentation shows **server**, **database**, and **last scan time**, ordered by `server` then `database`. The ordering key is deliberately independent of scan state so a given server holds the same position across runs. A candidate with no recorded scan is displayed as never scanned rather than blank, and its position in the ordering is unaffected.
- Interaction is gated on an attached terminal. With a terminal, the operator is prompted. Without one, resolution raises instead, listing every candidate and naming `--server` as the way to disambiguate — a scripted or scheduled run fails immediately rather than blocking on input.
- `--system_id` expansion validates each declared `{server, name}` against the registry **before any connection is attempted**, raising with the System, the offending pair, and where to register it. This validation is deliberately scoped to the scan path: the question-answering path performs no such check, because an unmatched pair there degrades safely to a cache miss that the service already handles, and blocking a question over a catalog typo would trade a real capability for a cosmetic one.
- The interaction point is injected into the existing target-resolution entry point as a callable defaulting to the real terminal prompt, rather than being called inline. No new module is introduced for it.

### Scan-cache visibility (`Impact_analysis_system` + `llamaindex-spec-rag`)

- A new read-only endpoint lists every SQL cache the service holds. Each row carries `server`, `database`, `schema`, and the recorded scan time. Rows are ordered by server, database, then schema.
- The listing enumerates cache **data** files and attaches the Scan Record from each sibling file when readable; a data file whose Scan Record is missing or unreadable is still listed, with an absent scan time. This preserves the existing rule that whether a Database is cataloged is determined solely by whether its cache file exists on disk — the endpoint reports that state, it does not maintain a second list of it.
- The endpoint is a thin pass-through over a listing function on the cache store; no analysis, no connection, no cache mutation.
- The **Database Registry** records intent (which Databases exist, on which server, scanned under which identity). The **Scan Record** records fact (whether a scan happened, and when). The two are never merged and a Scan Record is never copied into the Database Registry, so they cannot disagree. The caller reads facts through the endpoint at the moment it needs them.
- The caller gains a corresponding client function; `refresh_sql_cli` uses it to populate the last-scan-time column. It is fetched only when a choice actually has to be presented.

### Scan credentials (`llamaindex-spec-rag`)

- The **Scan Credential Override** changes from holding credential **values** (`uid`/`pwd`) to holding the **names of two environment variables** (`uid_env`/`pwd_env`). The values live in `llamaindex-spec-rag`'s `.env`, which this repo's config module already loads at import.
- Resolution rules, in order:
  - both fields blank → no override; the scan uses `Impact_analysis_system`'s global `DB_AUTH_MODE` identity, exactly as today;
  - exactly one field filled → raise. A half-applied edit is an error, not a fallback;
  - both fields filled but either named variable is unset or empty → raise, naming the variable that could not be read. Never fall back to the global identity, because a silent fallback resurfaces much later as an opaque SQL Server permission failure.
- Both `uid_env`/`pwd_env` are added to `.env.example` as commented examples so the mechanism is discoverable without a live secret.
- The `/refresh_sql` request contract is **unchanged**: the caller still sends the resolved credential pair by value. Only where the caller reads those values from changes. `Impact_analysis_system` requires no change for this, and the trust boundary it enforces — that the scan tool's identity never derives from a scanned application's own Web.config — is untouched.
- No credential, and no credential-variable name, is ever stored in `system_catalog.json`.
- The stale comment beside the registry path setting, which still asserts the file never stores credentials, is rewritten to describe the variable-name rule that now holds.

**This decision supersedes the credential-storage clause of the existing scan-identity decision, which specified `uid`/`pwd` values stored directly in the registry. It is not a refinement of that clause — it replaces it, and the original is annotated accordingly in its own repo.**

### `refresh_cli`'s uncataloged-database hint (`llamaindex-spec-rag`)

- The hint aggregates by the `(server, database)` pair rather than by database name, so two same-named databases on different servers report as two lines with their own counts.
- Each uncataloged database prints two lines: a directly runnable `--server`/`--database` scan command with both values filled in, and a follow-up line instructing the operator to register the database under that server in `SQLServerData.json` afterwards. The scan and the cataloging stay visibly separate steps.
- The server value is already carried on the wrapper observations the refresh response returns, and the review-item model already accepts extra keys, so this requires **no change to `Impact_analysis_system`** — only the caller-side reporting reads a field it was already being sent.
- `refresh_cli` still never writes to either catalog file and never triggers a live scan; the hint remains a suggestion a human acts on.

### Decisions to record

- The change from "a System declares Databases as a list of names" to `{server, name}` pairs supersedes the corresponding clause of the existing many-to-many decision. That decision's core claim — the registry is the sole registry of Database entities, independent of any System — survives unchanged; a System entry now *references* a registered Database by its full identity rather than by half of it. The reintroduced duplication between a System's declared pair and the registry is what the scan-path validation exists to keep from drifting, and that trade is recorded explicitly.
- Keeping intent (the Database Registry) and fact (the Scan Record) in separate files, and the refusal to merge them, is recorded as a decision.
- The inversion of `refresh_sql_cli`'s positional argument — a Database name positionally, a System behind a flag — is recorded as a decision, along with its reason: a System's declared dependency is a lookup of an already-fixed fact and must never prompt, while a bare database name is an operator supplying half an identity and legitimately may.
- Glossary entries for the terms this work makes load-bearing are added to `CONTEXT.md` before implementation, alongside the existing **Database** and **Shared Database** entries.

## Testing Decisions

A good test here asserts what an operator or caller observes: the resolved target list, the scan request actually issued, the reason a resolution refused, the exact hint text printed, or the rows a listing returns. It never asserts how many times a helper was called or in what order parsing happened. The existing suites already work this way — `refresh_sql_cli`'s tests replace the outbound scan call with a recorder and assert the recorded requests — and this work follows that shape.

**No new test seams are introduced. All four are existing.**

- **`source_resolver`'s public functions** — prior art: the existing source-resolver suite, which patches the catalog and registry loaders directly. Covers: `databases` parsed as `{server, name}` pairs; the System's cache source returned from the first declared pair without a registry lookup; the bare-name lookup returning zero, one, and several servers; server-address normalization matching short and named-instance forms; and every credential-resolution branch (both blank → no override; one filled → raises; both filled with a variable unset → raises naming it; both filled and readable → override returned). The existing assertion that the shipped catalog declares `databases` as a list of name strings is **currently failing** — the shipped file gained a third entry the assertion was never updated for — and is rewritten against the new shape rather than repaired against the old one.
- **`refresh_sql_cli.resolve_targets()` / `main()`** — prior art: the existing CLI suite's `monkeypatch`-of-`sys.argv` pattern plus its scan recorder. Covers: positional name resolving to exactly one server scans without interaction; zero servers raises with the `--server`/`--database` form in the message; several servers with the injected chooser present returns the chosen target; several servers with no terminal raises listing all candidates; candidate rows ordered by server then database with never-scanned rows shown as such and not reordered; `--system_id` expanding to every declared pair; `--system_id` validation raising on a pair absent from the registry, before any scan is issued; positional names combined with `--system_id` rejected; and `--server`/`--database` still bypassing the catalog entirely, guarded by the suite's existing "touching the catalog fails the test" helper.
- **`refresh_cli.main()` with captured output** — prior art: the existing refresh-CLI suite, which asserts the printed hint text directly. Covers: the two-line hint with server and database filled in; aggregation by `(server, database)` keeping two same-named databases on different servers as separate lines with separate counts; and deduplication to one entry per pair regardless of how many invocations hit it. The existing hint-text assertions are updated to the new wording.
- **The cache-store listing function (`Impact_analysis_system`)** — prior art: the existing SQL-cache-store suite and its cache-root fixtures, which write cache files to a temporary root and assert on filenames and parsed content. Covers: every cache present in the listing with its server, database, schema, and scan time; a data file with a missing or unreadable Scan Record still listed with an absent scan time; Scan Record files themselves never listed as caches; and deterministic ordering. The HTTP route is a thin pass-through and is **not** separately tested — this repo's suite has no API-level test precedent and tests service functions directly.

Migration of the four Declared Database Dependencies is a one-time hand edit of a hand-maintained file, not runtime code; it is covered by the rewritten shipped-catalog shape assertion rather than by a migration test.

## Out of Scope

- Any `primary`/`owned` marker distinguishing which of a System's declared Databases is its own. The first declared entry remains that System's SQL cache source, exactly as today. Raised during design, deliberately left unsettled.
- Automatically registering a discovered or scanned Database into `SQLServerData.json`. Registration stays a deliberate human edit; neither `refresh_cli` nor `refresh_sql_cli` writes to either catalog file under any code path. This was reconsidered during design and re-affirmed.
- Automatically triggering a live scan from `refresh_cli`. Unchanged.
- Validating declared dependencies on the question-answering path. Deliberately excluded above.
- Exposing cache format version through the new listing endpoint. It would let an operator spot caches on an outdated format that need re-scanning, which is genuinely useful — and is a separate concern from choosing between servers.
- Pagination, filtering, or any write capability on the new listing endpoint.
- Changing the `/refresh_sql` request contract, the scan-identity trust boundary, or anything about how `Impact_analysis_system` builds a scan connection.
- Moving `SQLServerData.json` into `Impact_analysis_system`. Considered and rejected: nothing in that repo reads it, its `config/` directory is version-controlled, and the caller needs the target list before issuing a request.
- Merging Scan Records into the Database Registry. Considered and rejected; the separation is recorded as a decision instead.
- Migrating, re-keying, or re-scanning any existing SQL cache. Cache identity and cache contents are untouched.
- Any change to how Web.config connection strings are parsed or how connection sources are resolved.
- Granting the scan identity read access to any newly registered Database. Still an operational step outside any spec.

## Further Notes

This spec is the output of a `/grilling` session run with the `domain-modeling` skill, across eleven rounds of frontier questions.

**Decisions carried from that session, verbatim.** Each was put to the user and confirmed; none may be quietly reversed during implementation. If any turns out to be unworkable, stop and raise it rather than substituting an alternative.

| # | Decision | Where it lands |
|---|---|---|
| 1 | The registry stays in `llamaindex-spec-rag`; `Impact_analysis_system` never reads it | Out of Scope |
| 2 | `refresh_cli` never auto-writes to any catalog; the hint is upgraded instead | `refresh_cli` hint; Out of Scope |
| 3 | `databases` stores `{server, name}` pairs — **reversed mid-session** from an earlier decision to keep bare names plus an error on ambiguity | Dependency shape |
| 4 | `refresh_sql_cli`'s positional is a database name; System moves to `--system_id`; zero → error, one → scan, several → chooser | Command line |
| 5 | A Scan Record is never merged into the Database Registry; a read-only endpoint exposes it instead | Scan-cache visibility |
| 6 | The registry stores environment-variable **names**; values live in `llamaindex-spec-rag`'s `.env`; an unreadable named variable raises and never falls back | Scan credentials |
| 7 | A positional name registered nowhere errors with the `--server`/`--database` form; it is never auto-registered | Command line |
| 8 | Interaction is gated on an attached terminal; without one, resolution raises listing the candidates | Command line |
| 9 | Candidates are ordered by `server` then `database` — **revised mid-session** from an earlier "never-scanned first", because a stable position matters more than a smart one when the operator is typing a number | Command line |
| 10 | Dependency validation runs only on the scan path, never on the question-answering path | Command line |

**On decision 3.** It was first settled the other way — keep bare names, and raise on ambiguity — on the grounds that no ambiguity exists today and the migration could wait. That reasoning was wrong in a specific way: it framed the complete-identity shape as an ergonomic improvement, when the actual consequence of bare names is that a true statement about the domain ("this System depends on the `PUR` on `vmsystest07`") cannot be written down at all. Nothing downstream recovers information the format cannot hold, and the `--system_id` mode would have failed on every invocation rather than in an edge case. The reversal is recorded here because the superseded reasoning is the more instructive half.

**On decision 6.** The prior spec in this area explicitly placed credential *values* in the registry, reasoning that the file is `.gitignore`d. That reasoning holds for version control and misses the actual exposure: the registry is the file an operator circulates when onboarding a server. Both fields are empty today, so this lands with no secret to migrate and no credential to rotate — which is precisely why it lands now rather than on the day someone needs the first override and writes a password inline to save five minutes.

**One clarification made while writing this spec, not settled during the session.** The half-filled override case — one of `uid_env`/`pwd_env` named, the other blank — was not put to the user. The prior rule treated a half-filled `uid`/`pwd` pair as unset and fell back to the global identity. This spec makes it **raise** instead, on the same fail-loud reasoning as decision 6. It is called out here rather than folded in silently; if the fallback behavior is preferred, say so and it changes.
