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

**Status:** ready-for-agent

- [ ] Both callers read the groups by name
- [ ] One function holds the denylist check
- [ ] The 20 tests in `tests/test_csharp_parser_method_declaration_shapes.py`
      and the `_METHOD_RETURN_TYPE_DENYLIST` tests pass without a change
- [ ] A rescan of RTTalentDB gives the same probe result as ticket 02
      (0 missing). The cache version does not change, because the scan output
      is the same

**Notes:**

- Source: the Standards axis of the code review of ticket 02 (2026-10-06).
- Keep CRLF in `csharp_parser.py`. Check `git diff --stat` before commit.
