# 02 — Confirm the fix on RTTalentDB and TOPCSCY's real scan caches

**What to build:** Re-scan (or re-parse) RTTalentDB's and TOPCSCY's Razor
views under the fixed parser and confirm their `ui_fields` now carry a
`data_field` for the single direct property bindings already found through
a non-`m`/`Model` parameter (`model => model.Property` in RTTalentDB,
`o => o.Property` in TOPCSCY), while the already-identified multi-level and
collection-indexed occurrences in both systems keep reporting raw `text`,
unchanged in count.

**Blocked by:** 01 — Match direct binding against the declared lambda
parameter, not a hardcoded `m`/`Model`

**Status:** done

- [x] RTTalentDB's refreshed scan cache shows a `data_field` for each of its
      single-property, non-`m`/`Model` bindings.
- [x] TOPCSCY's refreshed scan cache shows a `data_field` for each of its
      single-property, non-`m`/`Model` bindings, including the `o => o.`
      shape.
- [x] The previously-identified multi-level and collection-indexed
      occurrences in both systems still report raw `text`, with the same
      counts as before the fix.
- [x] No system-specific code change was needed to get this result.

## Note

Re-ran `service.scan_store.get_or_scan(root, refresh=True)` for both
`System_Dept_1/RTTalentDB` and `System_Dept_1/TOPCSCY`. Both scan caches now
record `cache_version: 39` (the version ticket 01 bumped to) against the same
`source_commit` as before, so the refresh re-parsed the same file set under
the fixed parser rather than picking up unrelated repo changes.

Verification method: parsed every `.cshtml` file in both systems with the
pre-fix parser (`git show e2d6832~1:code_analyzer/razor_parser.py`) and the
current parser, and diffed `ui_fields` file by file — a stronger check than
reading the cache alone, since it isolates exactly which entries the fix
touched.

- **RTTalentDB**: 9 entries across 3 files gained a `data_field` — all
  single-property `model.Property` bindings (`EmpID`, `Emp`,
  `ExperienceContent` ×2, `Score`, `Sort`, `ExperienceItem` ×2, `Point`) that
  previously fell back to raw `text` under the old hardcoded `m`/`Model`
  check. `data_field` count in the scan cache rose from 92 to 101 (+9); raw
  multi-level/collection-indexed entries held steady at 299 before and after.
- **TOPCSCY**: 0 entries changed. Every `model =>`/`o =>` lambda binding in
  TOPCSCY is either collection-indexed (`model.DataList[i].Property`,
  1867 raw entries) or multi-level (`o.Header.Property`, 57 raw entries) —
  TOPCSCY has no single-property non-`m`/`Model` binding to begin with, so
  the checklist item holds vacuously rather than by an observed flip.
  `data_field` count and raw multi-level/collection-indexed count (5826)
  were identical before and after.
- No entry lost a `data_field` in either system, and no entry changed for
  any reason other than gaining `data_field` (diffed with an exact
  structural comparison, zero unexplained diffs).
- No system-specific code path was touched to get this result — both scans
  ran the same unmodified `RazorParser` used for every other system.
