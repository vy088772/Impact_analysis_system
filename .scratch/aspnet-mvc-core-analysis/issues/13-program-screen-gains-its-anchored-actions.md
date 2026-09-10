# 13 — A Program Screen gains its anchored actions

**What to build:** A Program Screen's action set is complete: the actions whose name matches the
view, plus the actions its View Anchors name.

Ticket 10 delivers the first half. Without the second, every endpoint a screen
calls asynchronously is missing from its impact chain, including endpoints that
live on a shared controller with no view folder of its own. Such a shared
endpoint reaches a screen only through a candidate anchor, at `likely`, and is
reported that way rather than being attributed to every screen.

**Blocked by:** 10, 12.

**Status:** ready-for-agent

- [ ] A Program Screen holds the actions named by its determined View Anchors.
- [ ] A Program Screen holds the actions named by its candidate View Anchors, carried at `likely`.
- [ ] An action reached only through a candidate anchor is reported with that strength, never as determined.
- [ ] An action on a shared controller with no view folder reaches a screen only through that screen's own anchors.
- [ ] A controller appearing in two Program Screens contributes only the actions each screen anchors.
- [ ] The measured repository's AJAX detail query appears in its screen's impact chain.
