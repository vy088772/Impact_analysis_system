# 12 — View Anchors, determined and candidate

**What to build:** A view declares which actions its screen calls, and the analyzer records those
declarations at two strengths that are never merged.

A markup-layer declaration — an action attribute or a form action — is
determined. A controller-and-action shaped URL inside the view's own script
block is a candidate rated `likely`. One measured repository reaches its detail
query only through such a URL, so ignoring script blocks loses the endpoint
entirely; treating it as proven would dress a guess as evidence.

**Blocked by:** 11.

**Status:** resolved

- [x] A markup-layer action declaration is recorded as a determined View Anchor.
- [x] A form action is recorded as a determined View Anchor.
- [x] A controller-and-action shaped URL inside the view's own script block is recorded as a candidate View Anchor rated `likely`.
- [x] Determined and candidate anchors are carried separately in the result and are never merged.
- [x] A script-block string that does not have the controller-and-action shape produces no anchor.
- [x] An anchor naming a controller other than the view's own is recorded with that controller named.
- [x] The measured repository's AJAX-only detail endpoint appears as a candidate anchor on its screen.

## Comments

Implemented via TDD (red→green per slice), then a two-axis (Standards + Spec)
code review; both fixes below came out of that review pass.

**`code_analyzer/razor_parser.py`**: `RazorParser` now populates
`view_anchors_determined`/`view_anchors_candidate` (new `FileAnalysisResult`
fields, `code_analyzer/models.py`), extracted purely from the single view file
(no cross-file resolution needed, unlike ticket 11's displayed-field text).

Determined anchors come from three markup forms (matching CONTEXT.md's "View
Anchor" glossary entry exactly, not just the two the issue's own checklist
spells out):
- any tag carrying `asp-action` (optionally paired with `asp-controller` on the
  same tag, recorded as `controller` when present — the "names a controller
  other than the view's own" checklist line);
- any tag carrying `asp-page` (Razor Pages routing) — recorded as
  `{"page": "..."}`, a distinct shape from `action`/`controller` since it names
  a page, not a controller action; extracting the raw markup attribute is in
  scope for this ticket even though ticket 14 (blocked by this one) owns the
  separate page-model/code-behind handler pairing, a different mechanism;
- plain HTML `<form action="/Controller/Action">` — tolerant of trailing route
  segments (`/Order/Edit/5`) because the checklist states this one
  unconditionally, unlike the candidate line, which is explicitly qualified by
  shape.

Candidate anchors come from string literals inside the view's own `<script>`
blocks, kept to a strict two-identifier-segment shape (`_exact_controller_action`)
so a static asset path (`/Scripts/site.js`, `/Content/css/site.css`) never
produces one — a segment carrying a dot fails the identifier check, and a
extra path segment fails the exact-two-segment count. A query string
(`/Order/Detail?id=5`) is stripped before the shape check in both the form and
script paths, since a real AJAX call routinely appends one and losing the
anchor over it would defeat the ticket's own stated purpose.

Determined and candidate extraction never share a list or a code path — two
separate methods write to two separate `FileAnalysisResult` fields.

**`service/scan_store.py`**: `_CACHE_VERSION` bumped 33→34 — a cached
`FileAnalysisResult` from before this ticket has no View Anchors at all, the
same reasoning ticket 11 applied to `ui_fields`.

**Code-review findings applied**: the Standards pass flagged the tag-attribute
pattern being named `ASP_ACTION_TAG_PATTERN` while actually matching any
opening tag (renamed to `ANCHOR_TAG_ATTRS_PATTERN`) and a no-op `re.DOTALL`
flag on it (dropped). The Spec pass flagged three gaps, all fixed: `asp-page`
was missing entirely despite CONTEXT.md listing it as a determined form; the
form-action path originally applied the same strict two-segment shape check as
script candidates, which would have silently dropped an anchor for the
ordinary `Html.BeginForm("Edit", "Order", new { id })`-shaped route; and an
unrequested `~`-prefix strip (dead code — a literal `~/` only resolves through
a server-side helper, never as a raw HTML attribute) was removed. 3 new
regression tests added for these (`test_an_asp_page_attribute_is_recorded_as_a_determined_view_anchor`,
`test_a_form_action_with_a_trailing_route_segment_still_names_controller_and_action`,
`test_a_script_block_url_with_a_query_string_is_still_a_candidate_anchor`), on
top of the original 7 acceptance-criteria tests — 10 total in
`tests/test_razor_parser_view_anchors.py`.

Full suite: 794 passed / 11 failed (same pre-existing baseline as ticket 11,
confirmed unchanged) / 5 skipped.

