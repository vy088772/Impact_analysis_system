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

**Status:** ready-for-agent

- [ ] RTTalentDB's refreshed scan cache shows a `data_field` for each of its
      single-property, non-`m`/`Model` bindings.
- [ ] TOPCSCY's refreshed scan cache shows a `data_field` for each of its
      single-property, non-`m`/`Model` bindings, including the `o => o.`
      shape.
- [ ] The previously-identified multi-level and collection-indexed
      occurrences in both systems still report raw `text`, with the same
      counts as before the fix.
- [ ] No system-specific code change was needed to get this result.
