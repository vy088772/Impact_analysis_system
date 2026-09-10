# 11 — Razor view records carry displayed field text

**What to build:** An analyst can ask which fields a Core screen displays, and gets the text a user
would actually see.

The Razor parser produces the same structured record shape the WebForms parser
produces, so the view-layer summary, the flow chain builder and the snippet
extractor consume both without branching.

Field text comes from three sources, because the measured repositories use three
different conventions. One of them writes no readable label in the view at all:
its labels resolve through a display attribute on a model property to an entry
in a resource file.

**Blocked by:** 04.

**Status:** ready-for-agent

- [ ] Plain markup text in table headers and labels is extracted as displayed field text.
- [ ] A model-bound attribute contributes the model property it names.
- [ ] A display attribute carrying a literal label contributes that label with no resource lookup.
- [ ] A display attribute naming a resource entry contributes the entry's text.
- [ ] A display attribute whose resource entry is missing contributes nothing and says why, rather than contributing the key.
- [ ] The Razor view record shape matches the WebForms view record shape, and the view-layer summary renders both without special-casing.
- [ ] The scan cache version increments, because stored view records change shape.
- [ ] A view from each of the three measured conventions yields its displayed field text.
