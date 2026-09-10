# 10 — A Program Screen resolves to a view and its same-name actions

**What to build:** A specification program code resolves to one Program Screen: the view it names
and the actions whose name matches it (ADR-0019).

Base-name matching cannot do this. Across the measured repositories the program
name sits sometimes on the view folder, sometimes on the view file, and the
controller that serves it may carry an entirely different name. The existing
loose match also absorbs longer names, so a shorter program name swallows a
longer, unrelated one.

Resolution tries three entry points in order, and searches Area-qualified paths
the same way. WebForms program resolution is untouched and keeps its existing
path.

**Blocked by:** 04.

**Status:** ready-for-agent

- [ ] A program code naming a view folder resolves to that folder's views.
- [ ] A program code naming a view file resolves to that file, with an optional trailing `View` in the file name allowed.
- [ ] A program code naming a controller file resolves through it.
- [ ] An Area-qualified program code resolves, and two Areas holding same-named views do not collide.
- [ ] A match requires the whole name; a program code never matches a longer name that merely contains it.
- [ ] A resolved Program Screen holds one view and the actions whose name equals the view name.
- [ ] One controller serving three views yields three Program Screens, each holding only its own actions.
- [ ] A program code matching nothing is reported as not found.
- [ ] WebForms program resolution is unchanged, verified against the existing system.
