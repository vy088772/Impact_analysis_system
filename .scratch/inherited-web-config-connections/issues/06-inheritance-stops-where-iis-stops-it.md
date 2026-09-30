# 06 — Inheritance stops where IIS stops it

**What to build:** The analyzer applies the three IIS rules that block the
inheritance of a configuration entry. A child application that clears or
removes an inherited key does not resolve it. A parent section that IIS keeps
from child applications does not reach them. See the spec, section "Inherited
lookup tables".

**Blocked by:** 05 — A child web application resolves a connection its Parent
Application declares

**Status:** done (2026-09-30)

- [x] The `Web.config` parser reads `<clear/>` and `<remove>` in
      `<connectionStrings>` and in `<appSettings>`.
- [x] A `<clear/>` in a child section stops all inheritance for that namespace
      from above that level.
- [x] A `<remove name="..."/>` or `<remove key="..."/>` in a child section
      stops the inheritance of that one key.
- [x] A parent section inside a `<location>` element with
      `inheritInChildApplications="false"` does not pass to child
      applications.
- [x] A `<remove>` of a key that the same file adds later keeps the later
      entry, as IIS does.
- [x] Seam A tests cover each of the three rules.

## Comments

### 2026-09-30 — implementation notes

Files this ticket changed (other tickets run in parallel):

- `code_analyzer/webconfig_connection_resolver.py`: new `EntryBlocks`; the
  parser reads `<clear/>`, `<remove>`, and `<location>` in document order.
  `WebConfigConnections` gains `own_only_*` tables (sections in a
  `<location inheritInChildApplications="false">`) and `*_blocks`.
- `code_analyzer/connection_lookup.py`: `TableLayer` gains `blocks` and
  `stops()`. `_answer_from_table` ends the search at a layer that stops the key.
  Only the own layer holds the `own_only_*` entries. A layer that only clears
  is kept, so it still blocks. The guess shows only when no layer holds an entry.
- `tests/test_connection_lookup.py`: 15 new Seam A tests (section "Step 3").
- `docs/adr/0038-...md`: the two rules move from "later work" into the decision.

Decisions:

- A `<location>` element is read only when `path` is empty or `.`. Without the
  attribute (or with `true`) its sections pass to children like a normal
  section. Before this ticket the parser ignored every `<location>`, so this
  also makes such entries resolve for the own application.
- `<clear/>` or `<remove>` inside a `location` that blocks children does not
  stop inheritance from above.
- Case: `<remove>` matches a key with no regard to case, as `_find_key` does.
- A file with only `<clear/>` and a parent with entries: an unknown key gets no
  answer and no guess.

Test result: 1425 passed with `tests/test_search_roles.py` and
`tests/test_sp_tables.py` left out (same exclusion as ticket 05). The mypy
errors in `code_analyzer/parent_application.py` exist at HEAD, not from this
ticket. I did not run the multi-agent `/code-review`; I did a self-review.

### 2026-09-30 — code review

- Standards: no hard breach. Two items fixed: `CONTEXT.md` (Parent Application and
  Project Connection Scope) now names the three stop rules; the CRLF line ends of
  `webconfig_connection_resolver.py` are restored (a separate commit).
- Spec: the parser read every root section before every `<location>`, so a later
  root `<clear/>` did not clear an earlier `<location>` section. The parser now
  walks the children of the root in one document order. Two tests pin it. One
  new test pins a `<remove>` in an ancestor that stops the layers above it.
- Not changed, as a judgement: the smells in `_web_config_view` (Feature Envy,
  Data Clumps of the two namespaces) and the tuple keys of `_new_sections`;
  a `<clear/>` or `<remove>` inside a blocking `<location>` still stops nothing;
  an own-only entry beats a shared entry with the same key; a file with only
  `<clear/>` and no inherited entry still gives the key-as-name guess.
- Test result: 1428 passed (same two files left out).
