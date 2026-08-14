# 01 — Classify a wrapper method whose command comes from a data adapter

**What to build:** The wrapper decompiler finds a database operation in a method that builds its command through a data adapter, instead of through an explicit command object. After this ticket, decompiling the fixture assembly yields every public `CreateTable` overload it declares, and the two-argument overload carries a mode and a terminal sink.

Today the classifier keeps a method only when the method body constructs a command object. It drops any other method, and it records nothing about the drop. One real overload disappears this way.

Introduce **Command Source** as the named concept for the construct that supplies a method's command text and terminal sink. Put Command Source resolution behind one seam that holds a set of rules. Implement two rules: the existing explicit command object construction, and a data adapter construction that takes a command text argument and a connection argument.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] Command Source resolution sits behind one named seam, so that a later rule is one added entry and not a change to the surrounding flow.
- [x] A data adapter construction that takes a command text argument and a connection argument yields a Command Source.
- [x] A data adapter construction that takes an existing command object yields no second Command Source, because the first rule already covers that command object.
- [x] A method that resolves a Command Source through the adapter rule takes the mode `inline_sql`, unless the method assigns a stored-procedure command type.
- [x] The terminal sink for the adapter rule comes from the adapter fill call.
- [x] Decompiling the fixture assembly yields three `CreateTable` overloads.
- [x] The two-argument `CreateTable` overload carries the mode `inline_sql` and the terminal sink `Fill`.
- [x] Every other classified method of the fixture assembly keeps its current mode and terminal sink.
- [x] The end-to-end analyzer host test covers the three overloads, and it skips cleanly when the toolchain or the fixture checkout is absent.

## Answer

Introduced **Command Source** as the named concept for the construct that supplies a wrapper
method's command text and terminal sink, and put its resolution behind one seam.

- `WrapperAnalyzer.CommandSourceResolver` holds a `Rules` list. `CreateDefinition` no longer looks
  for a command object itself; it asks the resolver for the method's Command Sources and works from
  the first one. Each `CommandSource` carries its own terminal-sink resolver as a delegate, so a
  further rule is one added entry in `Rules` and nothing else — no enum member, no dispatch branch.
- Rule 1, the explicit command object construction, is behaviour-preserving. It still yields a
  source for a `SqlCommand` creation bound to no variable, so both the `multiple_sql_commands`
  verdict and the drop-the-method path trigger exactly where they did before.
- Rule 2 recognizes a data adapter construction with two arguments whose first is not an existing
  command object. Its command-property receiver is `<adapter>.SelectCommand`, so the mode is
  `inline_sql` unless the method assigns a stored-procedure command type; its terminal sink comes
  from the adapter's own `Fill`/`FillAsync` call.
- `Command Source` is now a glossary entry in `CONTEXT.md`.

Result on the fixture: `SQLFunc.dll` classifies 27 methods instead of 26. All three public
`CreateTable` overloads are present, and `CreateTable(String, String)` carries `fixed_inline_sql`
with the terminal sink `Fill` (`inline_sql` in the snapshot operation). Decompiling at the previous
commit and at this one and diffing the classified surface shows exactly one method added, none
removed, and none changed.

Validation:

- `dotnet build tools/StaticAnalyzerHost/StaticAnalyzerHost.csproj` passed.
- Ticket tests: `tests/test_command_source_resolution.py` (3 new) and the new overload test in
  `tests/test_wrapper_decompilation.py`, which asserts the whole classified surface as one map so a
  later rule cannot quietly change an unrelated method.
- Applicable full suite: 363 passed, 11 pre-existing failures (verified against a clean tree by
  stashing this change). `tests/test_search_roles.py` and `tests/test_sp_tables.py` cannot collect
  because the machine lacks `ODBC Driver 17 for SQL Server`.

Known limits, all deliberately left to other tickets:

- The stored-procedure "unless" is text-shaped: only the verbatim `adapter.SelectCommand.CommandType`
  form is seen, not an aliased `var cmd = adapter.SelectCommand`. Rule 1 has always had the same
  fidelity; semantic binding is Phase 2 (tickets 05/06).
- An adapter bound to no variable (`new SqlDataAdapter(sql, conn).Fill(ds)`) still yields no Command
  Source, and the method is dropped without a record. Recording every unclassified public method is
  ticket 02's deliverable, not this one's.
- A method holding a command object *and* an unrelated two-argument adapter now resolves to two
  Command Sources and so reports `multiple_sql_commands`, where it previously classified from the
  command object alone. No fixture method is affected, and the ambiguous verdict is the honest one.
