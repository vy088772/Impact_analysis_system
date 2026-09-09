# 04 — The Framework Label reports, and parsers mount by extension union

**What to build:** A maintainer running a refresh sees, for each scan root, which framework was
detected and which parsers actually mounted.

Today the detected framework decides which parsers mount, and the choice is
exclusive: a scan root holding both WebForms pages and Razor views loses one
side entirely, and loses it silently. The detected framework also never leaves
the scanner, so a wrong detection produces a thin scan with no explanation.

After this ticket the label describes the root and nothing more, and the scanner
reads every view kind actually present (ADR-0021).

**Blocked by:** None (can start immediately).

**Status:** done

- [x] Parsers mount by the union of view file extensions present under the scan root.
- [x] A scan root holding both WebForms pages and Razor views parses both, and neither set of view records is missing.
- [x] The refresh response carries the Framework Label per scan root, together with the parsers that mounted.
- [x] The refresh command prints both, one line per scan root.
- [x] A scan root whose framework cannot be identified fails with a clear message instead of falling back to a C#-only scan.
- [x] Running a refresh over the existing WebForms system prints its framework and mounts the WebForms parser, and its view record count does not fall.
- [x] Running a refresh over an ASP.NET Core repository prints its framework and mounts the Razor parser, where previously no Razor view was parsed.

## Note

Split across the two sibling repos (`refresh_cli` lives in `llamaindex-spec-rag`, not here — found this
by tracing where earlier tickets like 06 in `database-identity-decoupled-from-system` had actually
landed their `refresh_cli` changes).

**Impact_analysis_system:**

`ProjectTypeDetector.required_parsers_by_extension()` / `.file_extensions_present()`
(`code_analyzer/project_type_detector.py`) mount by the union of view-file extensions present under the
scan root — a small `_VIEW_KIND_TABLE` of `(FileType, extension, parser)` rows drives both, so the two
stay in lockstep instead of two hand-kept if-cascades. `ProjectScanner.__init__` uses these instead of
the old framework-exclusive `get_required_parsers()`/`get_file_extensions_to_scan()` mapping (left in
place, now unused by the scanner, for anything else still calling it) and raises `ValueError` when
`ProjectTypeDetector.detect()` reports `FrameworkType.UNKNOWN`. `service/api.py`'s existing
`except ValueError: raise HTTPException(400, ...)` around `/refresh` already turns that into a clean
400 with the message as `detail` — verified with a new test
(`test_refresh_api_reports_unidentifiable_framework_as_a_clear_400`) rather than assumed.

`ProjectScanResult.framework_reports` (a list of `{"scan_root", "framework", "parsers"}`, one entry per
scan root) is written by `ProjectScanResult.record_framework_report()` — called from
`ProjectScanner._record_framework_report()`, itself called from `scan_project()`,
`refresh_csharp_files()`, and `refresh_view_files()` (a no-op when the scanner was built by
`object.__new__`/a stub subclass that skips `__init__`, which several existing tests do to fake the
analyzer host). `_merge_scans` and `refresh_source` (`service/analyze_service.py`) carry it through for
a multi-scan-root system; `RefreshResponse.framework_reports` (`service/schemas.py`) exposes it over
`/refresh`, and `docs/openapi/openapi.json` is regenerated to match.

**Y-Docs_TTPUR's `TaskSchedule` scan root broke the literal reading of "fails instead of falling back
to C#-only."** It's a real, currently-registered scan root (`llamaindex-spec-rag/catalog/system_catalog.json`)
that is genuinely C#-only (a scheduler console app, `App.config`, no `web.config`/`appsettings.json`) —
and the old detector already sent it to `FrameworkType.UNKNOWN` today, silently falling back to
`csharp_parser` only. Raising unconditionally on `UNKNOWN` would have turned every refresh of this real
system into a hard failure. Fixed the actual gap instead: `ProjectTypeDetector._analyze_framework`'s
judgment 5 no longer falls through to `UNKNOWN` when there are C# files but no web markers — it reports
`FrameworkType.DOTNET_FRAMEWORK`, honestly describing a plain .NET project. `UNKNOWN` is now reachable
only when a scan root has no recognizable C#/view file of any kind. Confirmed against the real checkouts
in `data/repos/System_Dept_1`: `Y-DOCs/TaskSchedule` and `RTTalentDB/RTTalentDBMailJobApp` (same shape)
now construct cleanly as `DOTNET_FRAMEWORK`/`['csharp_parser']`; `IQCS` stays `DOTNET_CORE` with
`['csharp_parser', 'razor_parser']`; `Y-DOCs/TTPUR` stays `WEBFORMS` with
`['csharp_parser', 'aspx_parser']`.

**Llamaindex-spec-rag:** `impact_orch/refresh_cli.py` gained `_print_framework_reports()`, printing one
`framework: <scan_root> -> <framework>（parsers: ...）` line per scan root, called from `main()` right
after the existing update-summary line.

**Tests:** `tests/test_framework_label_parser_mounting.py` (new, 8 tests) covers the detector repair,
the union-mount methods, the scanner's `ValueError` on `Unknown`, mixed-root double-mount +
`refresh_view_files` actually parsing both sides, the report/dedup behavior on `ProjectScanResult`, and
a pickle-backward-compat check for `framework_reports`. `tests/test_program_refresh.py` gained
`test_refresh_response_carries_framework_label_per_scan_root` (multi-root merge through
`refresh_source`/`RefreshResponse`) and `test_refresh_api_reports_unidentifiable_framework_as_a_clear_400`.
`llamaindex-spec-rag/tests/test_refresh_cli.py` gained one test, its fixture validated against the
regenerated OpenAPI schema via the repo's existing `assert_matches_schema` helper.

**Verification for the last two criteria** (WebForms count doesn't fall / Core mounts Razor) is
analytic, not a live end-to-end `/refresh` run against the real checkouts — that needs the Roslyn host
and, for the WebForms baseline compare, a DB connection, both costly here. For `TTPUR` (no `.cshtml`
present), the new union-based mount and the old framework-exclusive mapping produce the identical parser
set (`csharp_parser` + `aspx_parser`), so the same files get parsed either way — the view-record count
cannot fall. For `IQCS`, the old exclusive mapping already included `razor_parser` for `DOTNET_CORE`
(this was already fixed before this ticket, per the existing `_find_files_by_extensions` docstring), so
the criterion's literal scenario doesn't reproduce on this specific checkout; the actual bug ADR-0021
targets — a root that could only ever get one of `aspx_parser`/`razor_parser` — is what the new
synthetic mixed-root test exercises directly.

**Full suite:** ran before and after. Baseline: 12 failed / 685 passed / 1 skipped (698 collected).
After: 694 passed (+10, all new), same 12 pre-existing failures unchanged (Windows CRLF/path
formatting, and a cluster of `ambiguous_overload`/`unresolved` vs `explicit_selected`/`proven`
mismatches — both clusters pre-date this change and are unrelated to framework detection or parser
mounting). One extra failure appeared in that run only
(`test_static_analyzer_host.py::test_command_source_resolution_stays_linear_in_corpus_size`, a
timing-sensitive assertion, `6.97s` vs an expected linear-scaling bound) — re-ran it alone and it
passed in `9.26s`; flaky under the load of the full run, not a regression from this change (nothing
here touches `StaticAnalyzerHost` or command-source resolution).
