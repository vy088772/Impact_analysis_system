# 12 — View Anchors, determined and candidate

**What to build:** A view declares which actions its screen calls, and the analyzer records those
declarations at two strengths that are never merged.

A markup-layer declaration — an action attribute or a form action — is
determined. A controller-and-action shaped URL inside the view's own script
block is a candidate rated `likely`. One measured repository reaches its detail
query only through such a URL, so ignoring script blocks loses the endpoint
entirely; treating it as proven would dress a guess as evidence.

**Blocked by:** 11.

**Status:** ready-for-agent

- [ ] A markup-layer action declaration is recorded as a determined View Anchor.
- [ ] A form action is recorded as a determined View Anchor.
- [ ] A controller-and-action shaped URL inside the view's own script block is recorded as a candidate View Anchor rated `likely`.
- [ ] Determined and candidate anchors are carried separately in the result and are never merged.
- [ ] A script-block string that does not have the controller-and-action shape produces no anchor.
- [ ] An anchor naming a controller other than the view's own is recorded with that controller named.
- [ ] The measured repository's AJAX-only detail endpoint appears as a candidate anchor on its screen.
