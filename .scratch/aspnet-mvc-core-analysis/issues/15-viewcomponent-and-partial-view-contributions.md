# 15 — ViewComponent and partial view contributions

**What to build:** A screen that renders a shared component reaches that component's stored
procedures, so the MVC path is not shallower than the WebForms user-control path
it corresponds to.

The contribution is labelled as coming from a shared component. Without the
label a component rendered on every screen — a menu, a selector — would put its
tables into every screen's answer with no way to tell them from the screen's
own.

**Blocked by:** 13.

**Status:** ready-for-agent

- [ ] A view rendering a ViewComponent reaches that component's stored procedures and tables.
- [ ] A view rendering a partial view reaches that partial's stored procedures and tables the same way.
- [ ] Every contribution reached this way is labelled as coming from a shared component.
- [ ] A component rendered by many screens contributes to each of them, and the label makes it distinguishable from the screen's own access.
- [ ] A component that reaches no database contributes nothing and produces no empty entry.
- [ ] A measured repository's selector component contributes its stored procedures to the screens that render it.
