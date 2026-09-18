# 01 — Filter `unresolved_connections` candidates by database-receiver type

**What to build:** The candidate-collection step that feeds
`unresolved_connections` — `ProjectScanner._invoked_connection_expressions()`
in `code_analyzer/project_scanner.py`, which currently gathers every
`source_wrapper` receiver expression out of a file's raw Database Invocations
into `tracker.invoked_connection_expressions` regardless of declared type —
now drops a receiver before it becomes a candidate at all when its declared
type carries no database signal. Reuse the same database-receiver-type
recognition that the four `connection_sources`-populating extraction paths in
`code_analyzer/db_connection_tracker.py` already require (Context Connection
Registration, Field-Held Connection, and their two sibling paths) — do not
build a second, hand-picked list of excluded types.

A receiver failing the type check produces no `unresolved_connections` entry
and no `connection_sources` entry — no trace in either report, as if the scan
had never treated it as a possible connection. A receiver passing the type
check keeps today's behavior unchanged: it resolves into `connection_sources`
on success, or keeps producing its `unresolved_connections` entry with its
existing reason on failure. `connection_sources` population itself does not
change — it was never the source of this noise.

No change to ADR-0018's Project Connection Scope design, and no per-system
configuration or exclusion list — the filter applies uniformly to every
scanned system.

Increment the scan-cache version convention (`_CACHE_VERSION` in
`service/scan_store.py`), since a cached scan from before this fix would
otherwise report the old, noisier `unresolved_connections` contents under a
cache-version number that claims to reflect the new behavior.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A receiver with a non-database declared type (an `IConfiguration` field
      read, an `HttpResponse` member access, a logging/email-service call)
      produces no `unresolved_connections` entry for that file.
- [x] A receiver with a database-shaped declared type that genuinely fails
      resolution still produces its `unresolved_connections` entry with its
      existing reason.
- [x] The existing `connection_sources` assertions in
      `tests/test_connection_field_resolution.py`
      (`test_project_scanner_records_a_field_held_connection`) and
      `tests/test_appsettings_connection_resolution.py`
      (`test_project_scanner_records_resolved_and_unresolved_connections`)
      keep passing unchanged.
- [x] Both new tests use the same seam as the prior art above:
      `ProjectScanner.refresh_csharp_files()` end-to-end into
      `ProjectScanResult.unresolved_connections` / `.connection_sources` on a
      `tmp_path` fixture project — never asserting which internal function did
      the filtering.
- [x] The scan-cache version number is incremented.

---

**Note (implementation):** Added `DBConnectionTracker.declared_type_of()` /
`declared_type_carries_database_signal()` / `is_plausible_connection_receiver()`
in `code_analyzer/db_connection_tracker.py`, sharing one recognition shape
(`SqlConnection` or `\w+Context`) with the four `connection_sources`-populating
paths (Context Connection Registration's `_ANY_CONTEXT_DECLARATION`, and
Field-Held Connection plus its two `SqlConnection`-literal siblings in
`_extract_sqlconnection_declarations`) — no separate exclusion list.
`declared_type_of` reads the declared type of a receiver expression's
left-most identifier (so `model.QryCond`/`this._config` resolve off `model`/
`_config`, not the whole dotted string, which no declaration ever matches
literally) and tolerates generics/arrays/nullable between the type token and
the variable (`IDictionary<string,string> attributes`, `object[] items`,
`string? x`) — both are plain bug fixes to declaration *discovery*, not
changes to the `SqlConnection`/`*Context` recognition rule itself.
`ProjectScanner._invoked_connection_expressions()` now takes `file_path`,
reads the file's source only when there are raw candidates to check, and
drops a candidate only when its declared type is found in the file *and*
fails that shared recognition; a receiver whose declaration cannot be found
at all is left alone (that gap already belongs to
`RECEIVER_DECLARATION_UNRESOLVED`, not to this filter). `_CACHE_VERSION`
bumped 37 -> 38 in `service/scan_store.py`.

Three new tests added to `tests/test_appsettings_connection_resolution.py`:
`test_project_scanner_drops_a_non_database_receiver_from_unresolved_connections`,
`test_project_scanner_drops_a_non_database_receiver_reached_through_member_access`,
and
`test_project_scanner_keeps_reporting_a_database_shaped_receiver_that_fails_resolution`.
All three drive a genuine `new SqlCommand(sql, receiver)` invocation through
the real StaticAnalyzerHost via `ProjectScanner.refresh_csharp_files()` (no
hand-fed `db_invocations`): an `IConfiguration` field, a `model.QryCond`
member-access off a non-database field, and an unregistered `LedgerContext`
field — and assert only on `ProjectScanResult.connection_sources` /
`.unresolved_connections`.

**Measured against real data, not just the fixture tests.** Ran
`/code-review` (Standards + Spec axes). The Spec reviewer checked this
against `data/scan_cache/d817e29ab991764b.pkl` (the IQCS cache the spec
itself cites) and found the first implementation — declared-type lookup
keyed on the *whole* candidate string, no generics/array/nullable support —
only dropped 124 of the 270 measured noise entries (46%), missing the
`model.QryCond`/`dt.Columns`-style member-access receivers and
`IDictionary<...> attributes`-style generic declarations entirely. Both
gaps above were added in response and verified against the same cache file
(not just re-reading the diff): 174 of 270 dropped (64%).

The remaining 96 entries are, by inspection, two irreducible categories
given this ticket's own constraint (reuse the existing
`SqlConnection`/`*Context` shape; no second hand-picked list; no semantic
model available to this regex-only recognizer):
1. A receiver rooted at a BCL/static type used directly (`DateTime.Now`,
   `string.IsNullOrEmpty`, `Regex.IsMatch`, `System.IO.File`, `Path`,
   `Console`) — no local declaration exists for `DateTime`/`string`/`Regex`
   *as a variable*, so `declared_type_of` correctly reports "unknown," and
   an unknown declared type is intentionally kept (dropping on "unknown"
   would risk hiding a genuine unresolved connection whose declaration this
   file-local regex simply can't see, e.g. one declared in a base class).
2. A receiver whose *locally declared* type coincidentally ends in
   `Context` but is a framework object, not a database context
   (`HttpContext context`, `ValidationContext validationContext`) — this is
   the exact shape `_ANY_CONTEXT_DECLARATION` already reuses; the four
   `connection_sources` paths have this same blind spot, so extending
   recognition past it would no longer be "the same recognition."

Neither category is fixable without either a hand-picked exclusion list or
real semantic binding — both explicitly out of scope for this ticket (see
spec.md's "Out of Scope" and Story 5). Recorded here so issue 02's spot-check
on STC/Y-DOCs TTPUR, and this ticket's own "269 of 270" motivating figure,
are read against what this fix actually does, not an inflated assumption.

Standards review (Fowler baseline; no repo-documented standard exists):
two judgement calls, neither acted on. (1) `declared_type_of`'s pattern
overlaps in shape with the pre-existing `_ANY_CONTEXT_DECLARATION`/
`SqlConnection`-literal regexes — left unmerged because those three belong
to `connection_sources` population, which this ticket must not touch by its
own "no change to connection_sources population" decision, and `declared_type_of`
now deliberately does more (base-identifier extraction, generics/arrays)
than any of them need. (2) `_invoked_connection_expressions` now carries
both ticket 17's and this ticket's reasoning in one docstring/method — left
as a natural extension of the existing seam rather than split, since the two
tickets share the same candidate set and the same caller.

Both listed prior-art tests, the three new tests, and the full
`tests/test_appsettings_connection_resolution.py` +
`tests/test_connection_field_resolution.py` suites, pass (33/33). Full suite
(`pytest tests/ --ignore=tests/test_search_roles.py
--ignore=tests/test_sp_tables.py`): 1041 passed, 11 failed — the failing set
is byte-identical to a `git stash` run against the unmodified base commit
(pre-existing external-wrapper-contract/IQCS failures, unrelated to this
ticket; the other two ignored files fail to collect on this machine for lack
of an ODBC driver, also pre-existing).
