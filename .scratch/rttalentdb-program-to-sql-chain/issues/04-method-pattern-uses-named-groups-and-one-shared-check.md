# 04 — `METHOD_PATTERN` uses named groups and one shared check

**What to build:** `METHOD_PATTERN` in `code_analyzer/csharp_parser.py` has a
return type group and a name group that callers read by position
(`group(7)`, `group(8)`). Two callers do this and each applies
`_METHOD_RETURN_TYPE_DENYLIST` on its own: `_extract_methods` and the HTTP
action scan. Ticket 02 widened the pattern to about 330 characters, so the
position reads are now fragile.

Name the groups (`ret`, `name`) or write the pattern with `re.VERBOSE`. Put the
"is this a declaration, not a statement" check in one function that both
callers use. The behaviour does not change.

**Blocked by:** None. Ticket 02 is done.

**Status:** done (2026-10-07)

- [x] Both callers read the groups by name
- [x] One function holds the denylist check
- [x] The 20 tests in `tests/test_csharp_parser_method_declaration_shapes.py`
      and the `_METHOD_RETURN_TYPE_DENYLIST` tests pass without a change
- [x] A rescan of RTTalentDB gives the same probe result as ticket 02
      (0 missing). The cache version does not change, because the scan output
      is the same

**Notes:**

- Source: the Standards axis of the code review of ticket 02 (2026-10-06).
- Keep CRLF in `csharp_parser.py`. Check `git diff --stat` before commit.
- Change: every group of `METHOD_PATTERN` has a name (`access`, `static`,
  `virtual`, `override`, `abstract`, `async`, `ret`, `name`). The pattern is
  a concatenation of short raw strings, not `re.VERBOSE`. The group numbers
  stay 1 to 8. With the `?P<...>` parts removed, the new pattern is the same
  string as the old pattern.
- `CSharpParser._is_method_declaration(match)` holds the denylist check.
  `_extract_methods` and `_extract_api_endpoints` call it.
- New test: `test_http_attribute_before_a_statement_gives_no_endpoint`. Before
  this ticket, no test covered the denylist check in the HTTP action scan.
  With the check disabled, this test and 6 of the old tests fail.
- The 20 old tests did not change. Full suite: 1777 passed (with
  `tests/test_search_roles.py` and `tests/test_sp_tables.py` left out, as in
  ticket 02). mypy shows the same 20 errors as before the change.
- Equivalence on all cached systems: old pattern with the old inline check
  against new pattern with `_is_method_declaration`, on each `.cs` file under
  each cached root. 2650 files, 12560 declarations, 0 files with a different
  match list (span, `ret`, `name`).
- RTTalentDB rescan (`f681f601165fe4e8`, cache version 45): 585
  `other-return` and 46 `tuple-return` in scan, 0 missing. This is the
  ticket 02 result.
- The rescan output differs from the old cache in the order of
  `MethodInfo.sql_queries` in 43 files. With each list sorted, the two scans
  are equal. The cause is `list(set(sql_queries))` in
  `_extract_sql_in_text`: the set order changes per process (string hash
  seed). This is not from this ticket. It makes a byte compare of two scans
  fail, so a scan compare must sort this list.
