# 03 — Remove the three MVC test files that assert nothing

**What to build:** Three test files in the suite contain zero assertions. They print to stdout and
return. One of them hard-codes an absolute path to a developer machine as the
project under test.

They pass today while verifying nothing, which is worse than having no test: a
green suite implies coverage that does not exist. The behaviour they gesture at
is specified properly by the tickets that follow, so removing them leaves no
gap.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [x] The three zero-assertion MVC test files are gone.
- [x] No remaining test hard-codes an absolute path to a developer machine.
- [x] The suite still passes, and its test count drops by exactly the removed files.

## Note

Removed `tests/test_mvc_project_scan.py`, `tests/test_mvc_parsing.py`, and
`tests/test_multi_parser.py`. Each printed to stdout and asserted nothing;
all three hard-coded `d:\TOPCSCY\Andy\TOPCSCY...` paths.

A repo-wide search for other hard-coded developer-machine paths in `tests/`
found none.

Collected test count before removal: 702. After removal: 698 (684 passed, 13
failed, 1 skipped). The drop of 4 matches the four test functions the three
files held (`test_mvc_project_scan`, `test_mvc_service`,
`test_project_detection`, `test_scanner_with_detection`).

The 13 remaining failures pre-date this change and are unrelated to it: they
belong to other in-flight tickets (`ambiguous_overload` vs `explicit_selected`
assertions match `optional-parameter-aware-overload-selection` and
`external-wrapper-surface-completeness`, both still `ready-for-agent`) or to
Windows-specific path/line-ending behavior (`WindowsPath` string form, CRLF
JSON output, a `PermissionError` on a temp file). None of the 13 touch the
three removed files or MVC/Core scanning.
