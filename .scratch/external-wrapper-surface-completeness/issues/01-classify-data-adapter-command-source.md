# 01 — Classify a wrapper method whose command comes from a data adapter

**What to build:** The wrapper decompiler finds a database operation in a method that builds its command through a data adapter, instead of through an explicit command object. After this ticket, decompiling the fixture assembly yields every public `CreateTable` overload it declares, and the two-argument overload carries a mode and a terminal sink.

Today the classifier keeps a method only when the method body constructs a command object. It drops any other method, and it records nothing about the drop. One real overload disappears this way.

Introduce **Command Source** as the named concept for the construct that supplies a method's command text and terminal sink. Put Command Source resolution behind one seam that holds a set of rules. Implement two rules: the existing explicit command object construction, and a data adapter construction that takes a command text argument and a connection argument.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Command Source resolution sits behind one named seam, so that a later rule is one added entry and not a change to the surrounding flow.
- [ ] A data adapter construction that takes a command text argument and a connection argument yields a Command Source.
- [ ] A data adapter construction that takes an existing command object yields no second Command Source, because the first rule already covers that command object.
- [ ] A method that resolves a Command Source through the adapter rule takes the mode `inline_sql`, unless the method assigns a stored-procedure command type.
- [ ] The terminal sink for the adapter rule comes from the adapter fill call.
- [ ] Decompiling the fixture assembly yields three `CreateTable` overloads.
- [ ] The two-argument `CreateTable` overload carries the mode `inline_sql` and the terminal sink `Fill`.
- [ ] Every other classified method of the fixture assembly keeps its current mode and terminal sink.
- [ ] The end-to-end analyzer host test covers the three overloads, and it skips cleanly when the toolchain or the fixture checkout is absent.
