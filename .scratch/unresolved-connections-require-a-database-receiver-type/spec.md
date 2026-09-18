# Unresolved Connection Candidates Require A Database-Shaped Receiver

Status: ready-for-agent

Found while comparing an IQCS scan cache against its source during a manual
review, then root-caused in a follow-up investigation
(`.scratch/unresolved-connections-require-a-database-receiver-type/` is that
investigation's own home). Companion to
`.scratch/razor-ui-fields-cover-html-for-helpers/`, found and root-caused in
the same review; the two are unrelated in cause and are tracked separately.

## Problem Statement

An analyst reading a scan's `unresolved_connections` report meets entries that
were never a database connection at all: a `.Response` redirect, a
`DateTime.Now` timestamp format call, an email-service call, a logging call,
a `Configuration Root Namespace` read that already resolved cleanly elsewhere
in the same file. Every one of these carries the same
`receiver_declaration_unresolved` reason a genuine unresolved connection
would carry, so nothing in the report tells the analyst which entries name a
real gap and which are noise the scan introduced on its own. In one measured
scan (IQCS), 269 of 270 entries across 95 files are this kind of noise. The
analyst has no way to tell that from the report itself, and a report an
analyst cannot trust by inspection is one they stop reading closely.

## Solution

A receiver becomes an unresolved-connection candidate only when its declared
type is plausibly database- or connection-shaped. The scan already carries
this judgment: Context Connection Registration, Field-Held Connection, and
their two sibling extraction paths — the code that populates
`connection_sources` — already require a receiver's declared type to match a
recognized database-context shape before attempting resolution. The
candidate-collection step that feeds `unresolved_connections` currently skips
that requirement and instead collects every `source_wrapper` receiver
expression out of a file's raw Database Invocations, regardless of type. It
now applies the same requirement the `connection_sources` paths already
enforce. A receiver whose declared type carries no database signal is
dropped before it ever becomes a candidate — it produces no
`unresolved_connections` entry, exactly as if the scan had never treated it
as a possible connection. A receiver that does carry a database-shaped type
and still fails to resolve keeps reporting its reason exactly as today.

`connection_sources` itself does not change. It was never the source of this
noise — it is written by the four extraction paths, which already carry the
type requirement this fix reuses — and this fix touches nothing about how a
receiver that passes the type check gets resolved or fails.

## User Stories

1. As an analyst, I want `unresolved_connections` to only list receivers that
   are plausibly database connections, so that I can act on every entry
   without first filtering out expressions that were never database-related.
2. As an analyst, I want the count of unresolved-connection entries to
   reflect real gaps in connection resolution, so that I can judge how
   complete a scan's connection coverage actually is from the number alone.
3. As an analyst, I want a receiver whose type is database-shaped but whose
   resolution genuinely fails to keep appearing in the report with its
   reason, so that the fix removes noise without hiding a real gap.
4. As an analyst, I want every `connection_sources` entry to stay exactly as
   it is today, so that a fix aimed at noise never touches an answer I
   already trust.
5. As a maintainer, I want the candidate filter to reuse the same
   type-recognition rule the four `connection_sources`-populating paths
   already apply, rather than a new hand-picked list of excluded types, so
   that one system's unrelated service interfaces never require a manual
   update to keep this rule working.
6. As a maintainer, I want this fix scoped to the candidate-collection step
   alone, without touching ADR-0018's Project Connection Scope design, so
   that the change stays as small as its actual cause.
7. As a maintainer, I want this fix to apply uniformly to every scanned
   system, so that a system other than IQCS sees the same noise reduction
   without any system-specific change.
8. As a reviewer, I want a test proving a non-database receiver (an
   `IConfiguration` field read, an `HttpResponse` member access, an
   email/logging service call) produces no `unresolved_connections` entry,
   so that the noise reduction is enforced rather than assumed.
9. As a reviewer, I want a test proving a genuine unresolved database-shaped
   receiver still appears with its existing reason, so that the filter's
   precision — not just its noise reduction — is under test.
10. As a reviewer, I want the existing `connection_sources` assertions in the
    current connection-resolution tests to keep passing unchanged, so that
    the fix is provably isolated to the unresolved side of the report.

## Implementation Decisions

- The candidate-collection step that currently gathers every raw Database
  Invocation receiver expression in a file (regardless of declared type) into
  the unresolved-connection check now applies the same database-receiver-type
  recognition the four `connection_sources`-populating extraction paths
  already require, before treating a receiver as a candidate at all.
- A receiver failing this type check is dropped from consideration entirely —
  no `unresolved_connections` entry, no `connection_sources` entry, no trace
  in either report.
- A receiver passing the type check keeps today's behavior unchanged: it
  resolves into `connection_sources` on success, or produces an
  `unresolved_connections` entry naming its existing reason on failure.
- No change to `connection_sources` population, to ADR-0018's Project
  Connection Scope, or to how a reason string is chosen for a receiver that
  passes the type check.
- Applies uniformly across every scanned system; no per-system
  configuration or exclusion list.
- The scan-cache version convention requires an increment: a cached scan
  from before this fix would otherwise report the old, noisier
  `unresolved_connections` contents under a cache-version number that claims
  to reflect the new behavior.

## Testing Decisions

A good test here asserts what ends up in `unresolved_connections` and
`connection_sources`, never which internal function did the filtering.

**Seam.** `ProjectScanner.refresh_csharp_files()` end-to-end into
`ProjectScanResult.unresolved_connections` / `.connection_sources`. This is
already the seam this area is tested at — prior art:
`tests/test_connection_field_resolution.py`
(`test_project_scanner_records_a_field_held_connection`) and
`tests/test_appsettings_connection_resolution.py`
(`test_project_scanner_records_resolved_and_unresolved_connections`) both
build a `tmp_path` fixture project, run the scanner, and assert directly on
these two fields.

- A receiver with a non-database declared type (an `IConfiguration` field
  read, an `HttpResponse` member access, a logging/email-service call)
  produces no `unresolved_connections` entry for that file.
- A receiver with a database-shaped declared type that genuinely fails
  resolution still produces its `unresolved_connections` entry with its
  existing reason, proving the filter is precise and not merely
  permissive-by-omission.
- The existing `connection_sources` assertions in
  `test_connection_field_resolution.py` and
  `test_appsettings_connection_resolution.py` continue to pass unchanged.

## Out of Scope

- The SP wrapper "observed vs assumed" command-mode distinction found during
  the same review. Investigated separately, confirmed as intentional and
  already tested behavior (see Further Notes) — no change.
- Any change to ADR-0018 or the Project Connection Scope design itself.
- `.scratch/razor-ui-fields-cover-html-for-helpers/` — tracked separately;
  unrelated cause, unrelated code.
- A positive-list registry of "database-shaped types" maintained
  independently of the four existing extraction paths. The fix reuses their
  existing rule rather than building a second one to keep in sync.

## Further Notes

- Originating review: a manual comparison of an IQCS scan cache
  (`data/scan_cache/d817e29ab991764b.pkl`, source commit
  `b6c8e9d676f61aca0951a31240cdab0d2844f89f`) against its source, which also
  surfaced the SP wrapper command-mode question above and the Razor
  `ui_fields` gap tracked in the companion spec.
- The SP wrapper question was first reported as a suspected systematic bug —
  a comparison between two call sites without reading one of the two sites'
  actual source line. A follow-up investigation found the two call sites
  differ in source (one passes the trailing argument explicitly, the other
  omits it and relies on the wrapper's own default), and that the analyzer's
  refusal to trust an omitted argument's default value is deliberate,
  commented, and covered by `tests/test_csharp_analysis_gateway.py`. It is
  recorded here only so a later reader does not re-open it from the same
  starting evidence.
- Spot-check systems named for verification once this fix lands: STC
  (`data/scan_cache/fbe54427b2bf7db0.pkl`) and Y-DOCs/TTPUR
  (`data/scan_cache/ee4df0cc3ec5f807.pkl`), in addition to IQCS.
