# Canonical Object Identity

Status: draft

This spec covers two repositories. This repository holds the analysis service.
The companion repository, `llamaindex-spec-rag`, holds the orchestrator and the
evaluation code. Both repositories change together.

## Preconditions

Two other specs delete code that this spec would otherwise merge. Both are
`ready-for-agent` and both have open issues. They land first.

- `remove-fk-cascade-tables` deletes the FK resolver module. That module holds
  one of the name-key implementations. This spec no longer names it.
- `retire-legacy-dependency-dictionary` deletes the dependency fetcher module.
  That module holds a second implementation. This spec no longer names it.

The merge issue of this spec checks both preconditions. It confirms that
neither module file exists before any merge starts. The test-fixture issue runs
before it. That issue touches no module either precondition spec deletes, so it
does not wait on them.

One more precondition is an operator action on another machine. This machine
cannot reach the SQL Server. An operator runs the refresh elsewhere and copies
the cache files here. The issues that depend on new cache files name this
precondition in their Blocked by line. No issue asks an agent to run a refresh.

## Problem Statement

An analyst asks "what breaks if I change this table?". Today the answer can name
the wrong table.

A SQL object name is written in up to four parts: server, database, schema, and
bare name. Every comparison in this system throws away everything except the
bare name. `dbo.Orders`, `sales.Orders`, and `OtherDb.dbo.Orders` all become
`orders`.

This is not a theoretical risk. The `Response` cache holds `dbo.Users`. Its own
stored procedures also read `PUR.dbo.Users` 39 times and `Common.dbo.Users` 6
times. The `ETON` cache reads `Pur.dbo.Users` 27 times. All four tables compare
as one name today, so one table's Execution Paths are reported against another
table's question.

The schema half of the same problem is worse, because the analyst cannot even
reach it. The refresh asks SQL Server for one schema at a time and defaults to
`dbo`. A Database with tables in `COMMON` and `HR` produces a cache that holds
neither. The analyst gets an empty answer and no warning that the question was
never asked.

Two sites discard the schema during extraction, not during comparison. The
regex table reader in the SQL analyzer and the table-name cleaner in the C#
parser both cut the name down before anything stores it. A schema that those
two sites drop is unrecoverable. No later module can put it back.

The rule that produces the key has no module. Twenty-three sites re-derive it
across the two repositories. They disagree in three ways. Nine sites fold case
with `lower` and the rest use `casefold`. Six sites strip brackets at the edges
only, and the rest remove every bracket. Two sites are whole schema-aware
splitters with the same contract and different cleaners. A change to bracket
handling therefore needs twenty-three edits, and no single place proves it.

## Solution

**Canonical Object Identity** — the rule that turns a written SQL object name
into a comparison key — gets one module. Every site calls it. The rule stops
discarding the schema and the database.

The module sits at the top level of this repository, beside `config`. Both
`service` and `code_analyzer` import it. It imports nothing from this project.
The `llamaindex-spec-rag` repository gets a mirror module of the same shape.

One SQL cache now holds one Database and every schema inside it. The **SQL Cache
Identity** (the normalized tuple that names one cache) drops its schema part and
becomes `(server, database)`. An operator runs one refresh per Database, not one
per schema. Each object in the cache carries its own schema.

The refresh lists every object kind in one query. Four listing methods that
differ only in a catalog view name and a column name become one. That one query
selects the schema beside the name, and the listing states the excluded-schema
rule once.

The StaticAnalyzerHost (the .NET host that runs Roslyn and ScriptDom) reads all
four name parts instead of the last two. A four-part reference keeps its
database. A reference that states no schema keeps an empty schema and is never
assumed to be `dbo`. The four parts then cross the host's JSON contract as four
named fields, so the Python reader stops applying the same lossy rule a second
time to the string the host produced.

A question that gives a bare name still answers. The bare name returns every
candidate, and the caller chooses. A question that gives a full identity answers
exactly. Both keys live in the Object Location Index (the record of every object
name one cache can answer for), so pruning stays authoritative under ADR-0012
and still over-reports rather than under-reports.

The SP Catalog (the set of stored-procedure names one SQL cache proves) already
holds both key shapes. It stops filling an unstated schema with `dbo`, which is
forced: it reads that default from the cache-wide schema field this work
removes. Both catalogs then answer under one written rule, and a match whose
schema nobody proved is reported with an **Unproven Schema** mark rather than
dropped.

The work runs in three steps. Step 1 merges twenty-three sites into one module
and changes one behaviour. Step 2a changes the write side and produces a cache
that carries schemas. Step 2b changes the read side and surfaces them.

Two preparatory issues run before Step 1, in order. The first routes every
test's cache payload through one builder. The second makes the SQL Cache
Identity the only way to name a SQL cache, so that Step 2a's removal of the
schema part is one edit in one value type rather than a list of nine sites.
Neither changes an answer this system gives, and every existing test returns the
same result before and after each of them. The second changes one behaviour no
test covers today: a repair run over the cache directory as it stands raises on
its first file, and after that issue it runs to the end.

## User Stories

1. As an analyst, I want `COMMON.AVM` and `dbo.AVM` reported as two different tables, so that an impact answer for one does not include the other's programs.
2. As an analyst, I want `PUR.dbo.Users` and `Response.dbo.Users` reported as two different tables, so that a cross-database reference does not merge into the local table.
3. As an analyst, I want a table in a non-`dbo` schema to appear in the cache at all, so that a question about it returns an answer instead of silence.
4. As an analyst, I want one refresh per Database to cover every schema in it, so that I never get an empty answer because nobody ran a second refresh.
5. As an analyst, I want a search by bare name to return every schema that holds that name, so that I can see the ambiguity instead of receiving one arbitrary answer.
6. As an analyst, I want an Execution Path whose schema is unproven to be reported and marked, so that I judge it myself rather than lose it.
7. As an analyst, I want a target whose schema is unproven to produce one Execution Path, and its table match to carry an Unproven Schema mark, so that one unknown fact never becomes several facts of which at most one is true.
8. As an analyst, I want the regex table reader to keep the schema it reads, so that a schema is not lost before any comparison can use it.
9. As an analyst, I want Step 1 to change one stated behaviour and no other, so that a refactor of this size is separable from a change of meaning.
10. As an analyst, I want the bracket form `[db].[schema].[table]` treated exactly like `db.schema.table`, so that the written style of a name never changes the answer.
11. As an analyst, I want a name that states no schema to stay unproven rather than be labelled `dbo`, so that a wrong schema is never presented as a fact.
12. As an analyst, I want a stored procedure my C# code names with a schema to keep matching the catalog, so that separating schemas does not lose a match I get today.
13. As an analyst, I want a cross-database reference to carry its own Database into the index, so that one cache's evidence is never reported as another Database's table.
14. As an analyst, I want a name written without a database inside a stored procedure read as that Database's name, so that a local table still answers a fully qualified question.
15. As an operator, I want one refresh command per Database with no schema option, so that I cannot produce a half cache by forgetting a schema.
16. As an operator, I want the cache filename to name the server and the Database only, so that the filename stops claiming a schema scope the cache no longer has.
17. As an operator, I want every cache built before this change to invalidate itself, so that a stale single-schema cache cannot be read as if it were complete.
18. As an operator, I want no migration tool to run, so that I do not maintain a tool that cannot produce the data it would need to migrate.
19. As an operator, I want system schemas excluded from the refresh, so that the cache does not grow with objects no analyst will ever ask about.
20. As an operator, I want the excluded schema list fixed in code, so that I do not maintain one list per Database as the catalog grows past a hundred.
21. As an operator, I want to confirm Step 2a by opening one copied cache file and finding a non-`dbo` schema, so that I do not start Step 2b against a cache that never changed.
22. As an operator, I want a refresh that fails on one schema to fail the whole Database, so that a partial cache never looks complete.
23. As an operator, I want no issue to ask an agent to run a refresh, so that a machine with no route to the SQL Server can still finish its issues.
24. As an operator, I want the five existing caches replaced before the read side changes, so that four Databases do not fall silent while the tests stay green.
25. As a caller, I want `/locate_object` to report a schema for each match, so that I can act on the answer without opening the cache myself.
26. As a caller, I want one Database with three schemas to produce three rows, so that I can tell which schema holds the name.
27. As a caller, I want the Declared Database Dependency comparison to keep reading only server and database, so that adding the schema field breaks no existing match.
28. As a caller, I want the `db_schema` field removed from the refresh request and the scan record, so that no field survives that no longer means anything.
29. As a caller, I want both repositories deployed together, so that the removed field never reaches a service that still requires it.
30. As a caller, I want the cache identifier to change when the cache shape changes, so that a stale routing expectation is detected rather than trusted.
31. As a caller, I want every routing expectation regenerated after Step 2a, so that expectations describe the cache that now exists.
32. As a caller, I want one shared fixture file in this repository to hold both the name cases and the cache identity cases, so that the cross-repository agreement never depends on which cache files sit on an operator's disk.
33. As a caller, I want every object-key function in the evaluation repository updated in the same change, so that none of them keeps merging schemas the cache now separates.
34. As a caller, I want a located-database row to keep naming the cache it came from, so that narrowing the Candidate Database Set never drops the cache that holds the evidence.
35. As a caller, I want a cross-database match to name the Database its key states, so that I can act on the answer without opening the cache.
36. As a reviewer, I want one module to own the rule, so that a change to bracket handling is one edit and one test.
37. As a reviewer, I want the module to import nothing from this project, so that a string rule never drags an analysis graph into a caller.
38. As a reviewer, I want both layers to import the module downward, so that this change adds no new dependency direction between them.
39. As a reviewer, I want the stored-procedure side and the table side to share the rule, so that the two cannot disagree about a bracket or a separator.
40. As a reviewer, I want `casefold` used everywhere instead of `lower`, so that two spellings of case folding stop coexisting.
41. As a reviewer, I want the case-folding change named in the spec as the one intended behaviour change in Step 1, so that it is not mistaken for a regression.
42. As a reviewer, I want both existing schema-aware splitters absorbed rather than one, so that no diverging copy of the correct behaviour survives.
43. As a reviewer, I want the case-preserving variant kept beside the key function, so that a caller building a pattern does not re-derive half the rule.
44. As a reviewer, I want the parse function to return an empty schema and never a default, so that the module's own contract holds from the first commit.
45. As a reviewer, I want the Object Location Index to hold a bare-key bucket and a full-key bucket, so that both question shapes answer from the index alone.
46. As a reviewer, I want the index to keep over-reporting rather than under-reporting, so that this change cannot lose an answer that ADR-0012 promised.
47. As a reviewer, I want the analyzer to read named ScriptDom properties instead of slicing a list, so that a four-part reference keeps its database.
48. As a reviewer, I want the analyzer's JSON contract version raised on both sides of the subprocess, so that an old host and a new reader cannot silently disagree.
49. As a reviewer, I want an ADR recording why one cache now holds one Database, so that a future reader understands why the identity lost its schema part.
50. As a reviewer, I want `CONTEXT.md` to define Canonical Object Identity, so that the term is used consistently instead of reinvented.
51. As a reviewer, I want the `CONTEXT.md` SQL Cache Identity entry corrected, so that the glossary stops describing a tuple that no longer exists.
52. As a reviewer, I want the cache store docstring corrected, so that a comment stating the old collapse behaviour does not contradict the code.
53. As a reviewer, I want the SP Catalog to stop substituting a default schema, so that one rule about an unstated schema holds in both catalogs.
54. As a reviewer, I want an Evidence Status to stay proven when only the schema is unproven, so that a schema distinction does not silently change a downstream path decision.
55. As a reviewer, I want both catalogs to obey one written lookup rule instead of sharing a module, so that the rule is checkable without a dependency between them.
56. As a reviewer, I want Unproven Schema to be one term in the glossary, so that the Execution Path mark and the catalog reason use the same word.
57. As a maintainer, I want the module testable with strings alone, so that a test of the rule builds no graph and opens no cache.
58. As a maintainer, I want the twenty-three sites listed by module, so that the merge is checkable rather than approximate.
59. As a maintainer, I want the two deleted modules confirmed absent before the merge starts, so that I do not merge a rule into code another spec is removing.
60. As a maintainer, I want the normalizers for paths, program names, servers, and contracts left alone, so that the merge does not swallow unrelated concepts.
61. As a maintainer, I want Step 2 split into a write side and a read side, so that an empty result in Step 2b is traceable to one of the two.
62. As a maintainer, I want one issue to touch one repository, so that each issue is accepted inside the repository it changes.
63. As a maintainer, I want the SP Catalog change to land in the listing commit that removes the cache-wide schema field, so that no commit leaves the catalog half-changed.
64. As an operator, I want one query to list every object kind, so that a refresh makes one round trip instead of four.
65. As a reviewer, I want the excluded-schema rule written once, so that a change to that rule is one edit.
66. As a reviewer, I want a schema named `dbXyz` kept by the listing, so that the `db_` rule excludes only what it names.
67. As a reviewer, I want the listing to return a named tuple, so that no caller splits a qualified string to recover the schema.
68. As a maintainer, I want the full-database dump to lose its schema argument, so that no argument survives that selects nothing.
69. As a maintainer, I want no compatibility wrapper for the old bare-name listing, so that no site keeps dropping a schema.
70. As an operator, I want the interactive menu to print `schema.name`, so that I can tell two same-named procedures apart before I choose one.
71. As an analyst, I want a procedure in a non-`dbo` schema to keep its full definition, so that an unbracketed name never produces an empty body.
72. As a reviewer, I want one helper to compose every qualified name, so that a reserved word inside a name cannot break one site and spare another.
73. As a reviewer, I want the graph builder to read each object's own schema, so that one cache file never states two schemas for one object.
74. As an operator, I want the five existing caches to keep loading after the listing change, so that no Database falls silent earlier than it must.
75. As an operator, I want a record of every bare name that two schemas hold, so that I can measure the collision before Step 2b removes it.
76. As a maintainer, I want the listing commit to delete the cache-wide schema field and its three readers, so that no cache states a schema that the dump no longer knows.
77. As a maintainer, I want the native dependency dictionary left alone, so that this change does not absorb code another spec removes.
78. As a reviewer, I want every schema argument and field in the static analyzer to lose its `dbo` default in Step 1, so that a caller with no stated schema raises instead of silently matching `dbo`.
79. As a reviewer, I want the analyzer to carry four named parts instead of one joined string, so that no reader splits a name the analyzer already parsed.
80. As an analyst, I want a reference that states a database and skips the schema to keep its database, so that a Database name is never reported as a schema.
81. As a reviewer, I want the analyzer's name reader to drop its textual fallback, so that an unexpected fragment returns nothing instead of a name guessed from dots.
82. As a reviewer, I want the analysed module's own identity to carry no database field, so that no field exists that the language can never fill.
83. As a reviewer, I want an unrecognised module to report an empty schema, so that one rule about an unstated schema holds everywhere in the host.
84. As a reviewer, I want function-call references to carry the same four parts, so that one kind of object reference does not keep the old flattening.
85. As an analyst, I want a table question for `dbo.AVM` to return nothing when the graph holds only `COMMON.AVM`, so that a stated schema that differs never matches.
86. As an analyst, I want a question that states a schema to match a target that states none, with an Unproven Schema mark, so that an unqualified reference inside a stored procedure is still reported.
87. As an analyst, I want a proven write whose target schema is unproven to stay in a `write_only=True` answer, so that a schema distinction never hides a write.
88. As an analyst, I want a table match record to name the table as the graph stores it, so that a schema my question supplied is never presented as evidence.
89. As an analyst, I want a bare-name table question to return one record per schema that holds the name, with no mark, so that a proven schema is never labelled unproven.
90. As an analyst, I want a table reached through a View or a Function to obey the same match rule, so that lineage does not keep the bare-name merge.
91. As a caller, I want each Execution Path to carry its read and write targets as full keys with named fields, so that I never split a target name to recover its database.
92. As a caller, I want a table match record to carry `stated_database` when the matched key names another Database, so that I can act on a cross-database answer without opening the cache.
93. As a caller, I want the Unproven Schema rule to leave the `path_id` formula unchanged, so that both deduplication sites and `/path_evidence` keep reading one identity as one path.
94. As a reviewer, I want an ADR recording why an unproven schema does not multiply an Execution Path, so that nobody proposes one path per candidate schema again.
85. As a reviewer, I want duplicate removal to compare all four parts, so that two references that state different databases stay two references.
86. As a maintainer, I want a test to assert that the two contract version constants agree, so that raising one and forgetting the other fails before the analyzer ever runs.
87. As an analyst, I want a reference that states no schema to answer exactly as it does today, so that this change moves only the names it set out to move.
88. As a caller, I want each Execution Graph relationship to carry the database its reference stated, so that the read side reads a field instead of parsing a name again.
89. As a reviewer, I want a referenced node to carry no database, so that two references that disagree cannot leave one of their databases on the node they share.
90. As an operator, I want a stale Execution Graph rebuilt from the definitions already on this machine, so that a graph shape change never waits for a SQL Server refresh.
91. As an operator, I want no rebuild on the query path, so that one question never blocks for minutes behind a graph rebuild.
92. As a maintainer, I want the graph format version to rise whenever the graph payload shape changes, so that two different shapes never claim one version.
93. As a maintainer, I want one shared helper to build a four-part reference from a short written name, so that a test about graph queries stays about graph queries.
94. As a caller, I want the server normalization rule covered by the shared fixture, so that the two repositories stop computing different keys for one server.
95. As a maintainer, I want one test fixture module to be the only way a test gets a payload, a version, or an analyzer operation, so that a shape change breaks one file instead of twenty-three.
96. As a maintainer, I want a check that fails when a payload key, a version literal, or an operation key appears outside the fixture module, so that the module's one source is checkable rather than approximate.
97. As a maintainer, I want the in-memory reader stubs to take their payload from the builder, so that a test that bypasses the reader cannot pass against a shape no cache holds.
98. As a maintainer, I want the payload builder to take each object as a written name, so that a test states which schema holds a name instead of restating the payload shape.
99. As a maintainer, I want the Execution Graph payload built by its own helper, so that one builder never owns two format versions that rise in two commits.
100. As a maintainer, I want every payload's graph version read from the graph module's constant, so that no test asserts against a version number it wrote itself.
101. As a maintainer, I want the fixture's write helper to take a SQL Cache Identity, so that no test composes a cache filename by hand.
102. As a maintainer, I want the fixture's meta file written by the cache store's own meta writer, so that the meta format stays defined in one place.
103. As a maintainer, I want a separately named helper for a key no identity can produce, so that a deliberate legacy key is visible at the call site.
104. As a maintainer, I want the fixture work in its own issue with no behaviour change, so that the whole suite's result is identical before and after it.
105. As a reviewer, I want the SQL Cache Identity to lose its schema field in Step 2a, so that a caller that still names a schema fails instead of reading a schema nobody holds.
106. As a maintainer, I want every cache-store function to take a SQL Cache Identity, so that removing the schema part is one edit rather than a list I must enumerate correctly.
107. As a maintainer, I want the identity's constructor to stay pure, so that building one never reads the cache directory.
108. As a maintainer, I want a separately named function for a caller that knows no server, so that "reads the disk and may find nothing" is visible at the call site.
109. As a maintainer, I want the ambiguous-server case to return a value, so that a test can state it instead of observing it through a reader's side effect.
110. As a maintainer, I want each call site to state which of the two it asks for, so that no function takes a server that may or may not be there.
111. As a reviewer, I want the identity's `dbo` default removed in the preparatory issue, so that Step 2a deletes a field instead of hunting defaults at the same time.
112. As a reviewer, I want that reversal written into this spec beside the rule it reverses, so that a decision changes in the open rather than in silence.
113. As a maintainer, I want the identity to own its three filenames, so that nothing else composes or filters a cache suffix.
114. As a maintainer, I want the reverse parse to sit beside the forward compose, so that a two-part filename can never be read by a three-part rule.
115. As a maintainer, I want the reverse parse to return nothing for a stem that names no identity, so that a stray file is never reported as a partial one.
116. As a maintainer, I want the in-memory cache keyed by the identity, so that nothing inside the module parses a key string back into fields.
117. As a maintainer, I want the meta writer to take the identity alone, so that the path it writes to cannot disagree with the identity it records.
118. As an operator, I want `/scan_records` to keep listing a file whose name states no identity, so that an unrecognised file stays visible instead of disappearing.
119. As an operator, I want `/scan_records` to report the same fields it reports today, so that this preparatory work changes nothing I read.
120. As an operator, I want a hand-edited Scan Record to produce a row rather than a failed request, so that one bad file never hides every other cache.
121. As an operator, I want the graph repair tool to run to completion, so that Step 2a's recovery is a plan I can actually execute.
122. As an operator, I want the repair tool to ask the cache store which files are caches, so that a suffix added later cannot be missed by a second copy of the list.
123. As a maintainer, I want the one-off key-migration tool deleted, so that no tool survives that migrates to a filename shape this work removes.
124. As a reviewer, I want `CONTEXT.md` to record that the identity owns its filenames, so that a future reader does not build a second suffix list.
125. As a reviewer, I want the index to state its own format version, so that a change to the index shape invalidates every index on disk.
126. As a maintainer, I want every graph format version in a test read from the graph module's constant, so that a stale value cannot sit in a test that never validates it.
127. As a maintainer, I want the twelve stale graph versions decided by one rule, so that a per-file judgement is not made twelve times with twelve chances to differ.
128. As a maintainer, I want a test that needs another version to write it relative to the constant, so that a deliberate version reads as deliberate.
129. As a maintainer, I want every contract version in a test read from the client's constant, so that raising that constant breaks no test that only restated it.
130. As a maintainer, I want the contract mismatch raise covered by a test, so that the client's rejection is proven rather than assumed.
131. As a maintainer, I want one shared helper to build an analyzer operation, so that Step 2a changes one helper instead of five test files.
132. As a maintainer, I want a contract test to keep writing the operation shape out in full, so that the test that states the shape is not the test that hides it.
133. As a maintainer, I want the check to exclude its own file by path, so that the check's own rule strings never fail its own rules.
134. As a maintainer, I want the check to read the test directory alone, so that a constant's own definition is never reported as a violation.
135. As a maintainer, I want the check to allow a bare number beside the constant it pins, so that the assertion on the constant survives with no file-name exemption.
136. As a maintainer, I want the fixture issue's two suite runs compared by test identifier, so that one broken test cannot hide behind one newly passing test.
137. As a maintainer, I want the fixture issue split one commit per shape, so that one shape's move reverts without the other three.
138. As a reviewer, I want the spec to state why three decompile-wrapper files join this issue, so that a later reader does not infer a subject they do not share.
139. As a maintainer, I want the SQL Cache Identity issue to wait for the whole fixture issue, so that the fixture issue's proof covers an interval nobody else changed.
140. As a reviewer, I want `CONTEXT.md` to record the test fixture module as the one source of every shape, so that the rule does not live only inside the check that enforces it.
141. As a reviewer, I want the identity commit's site list written against the code the preparatory issue leaves behind, so that the list does not name sites that issue already removes.
142. As a reviewer, I want the identity commit to name every site that still reads a schema, so that its completeness does not depend on which code a test happens to reach.
143. As a reviewer, I want a grep check in the identity commit's acceptance, so that a site the list misses still fails the commit.
144. As a caller of `/find_by_sp` or `/find_by_table`, I want the server reverse-derivation to match on the identity's Database field, so that a two-part filename still finds its cache.
145. As a maintainer, I want a test for a Database name that holds `__`, so that a change in the number of filename parts cannot mis-split that name in silence.
146. As a maintainer, I want the meta file and the Object Location Index to lose their `schema` field in the identity commit, so that no reader compares a field the identity no longer holds.
147. As a maintainer, I want tests that describe two caches for one Database deleted with the identity commit, so that no test asserts a state the cache format cannot produce.

## Implementation Decisions

### The `dbo` default in the static analyzer

Sixteen sites in this repository's static analyzer default a schema argument or
field to `dbo`. No caller states that default; the code states it for them.

This is a different defect from the twenty-three sites the new module absorbs.
Those sites re-derive a comparison key. These sixteen sites pass a schema
straight into a SQL query, or hold it as a stored field.

Every one of these sixteen sites loses its default value, in Step 1's first
commit:

- The four listing methods.
- The per-object fetches: object definition, function parameters, primary-key
  columns, and table columns.
- The full-database dump. Its schema argument loses only its default here.
  Step 2a removes the argument itself, once the dump stops taking one schema
  at a time.
- The quick single-procedure analyzer, and the native-table lookup it calls
  internally.
- The batch analyzer.
- The write-info lookup. It has no caller in this repository today.
- The schema field on the quick-analysis result and on the full analysis
  result.

One site keeps its default: the native dependency dictionary method. It has no
caller in this repository, and the `retire-legacy-dependency-dictionary`
precondition removes its readers, as the Out of Scope section already states.

The change touches no site in `llamaindex-spec-rag`. It also leaves the
identity chain alone, because a separate preparatory issue handles that chain
first. The SQL Cache Identity, the cache filename, and the refresh CLI lose
their `dbo` default under "The SQL Cache Identity module", not here and not at
Step 2a.

An earlier draft of this section kept that default until Step 2a, on the ground
that those sites double as the cache key. That ground does not hold. Removing a
default changes no computed filename: a caller that stated nothing now states
`dbo` itself, and the key is the same string either way. Keeping the default
would leave Step 2a hunting sixteen-plus defaults at the same time as it deletes
the field they default to.

Eight call sites reach one of these sixteen without stating a schema today:

- Five call sites in the C# project scanner call the quick single-procedure
  analyzer.
- The interactive menu's single-procedure path calls the four listing
  methods' procedure listing.
- The interactive menu's batch path calls the batch analyzer.
- One construction builds an empty quick-analysis-result shell, from existing
  definition text, with no schema of its own.

Each of these eight passes `dbo` explicitly instead of relying on the default.
A comment at each site names Step 2b as the step that removes it.

Two more sites have no caller at all: the write-info lookup, and the schema
field on the full analysis result. Their defaults are removed with no caller
to update.

No answer changes in this commit. A caller that used to receive `dbo` from
the default now states `dbo` itself. A caller nobody has written yet, and any
caller a future edit misses, raises `TypeError` instead of reading `dbo`.

### The Canonical Object Identity module

- One new module owns the rule. It sits at the top level of this repository, as
  a single file named after the glossary term. It is not a package directory,
  because the repository holds exactly one such rule.
- The placement follows `config`. That package is the existing precedent for a
  top-level module that both `service` and `code_analyzer` import. Today
  `service` imports `code_analyzer` 26 times and `code_analyzer` imports
  `service` never. A module inside `service` would reverse that direction for
  the five sites in `code_analyzer`, so the module sits outside both.
- The module imports nothing from this project. The nearest existing home, the
  graph query module, transitively pulls in the C# analysis gateway. A string
  rule must not drag a whole analysis stack into four cache fetchers.
- The module exports a frozen value type with three fields: database, schema,
  and bare name. An empty field means "not stated", never "default".
- The module exports a parse function, a bare-key function, and a full-key
  function. The bare key is today's behaviour exactly. The full key composes all
  three parts.
- A full key always holds three segments. An empty part stays an empty segment,
  and the separator stays. The name `Orders` therefore produces `..orders`. A
  full key that dropped its empty segments would equal the bare key, and the two
  buckets could then never differ.
- The parse function always returns an empty schema for a name that states no
  schema. It takes no default-schema argument, in Step 1 or later.
- The module also exports a case-preserving variant of the bare name. One caller
  builds a regular expression from a procedure name and needs the original case.
  It currently re-derives half the rule to get it.
- All case folding uses `casefold`.

### Which sites the module absorbs

Twenty-three sites. Nineteen sit in this repository and four sit in
`llamaindex-spec-rag`.

This repository:

- The four cache fetchers: stored procedure, stored-procedure call,
  user-defined function, and view. Five functions, because the stored-procedure
  call fetcher also holds the case-preserving variant.
- The flow chain builder and the graph query module. One function each.
- The execution path builder. Three functions: name, schema, and database.
- The analysis service. Two functions: a table normalizer and a schema-aware
  splitter.
- The SQL execution graph builder. One function: a second schema-aware splitter
  with the same contract as the analysis service's and a different identifier
  cleaner.
- The C# analysis gateway. Four sites: the three stored-procedure-side functions
  for name, schema, and schema-name, plus one inline re-derivation that sits
  beside a call to one of them.
- The C# parser's table-name cleaner. It is an extraction site, and it drops the
  schema before anything stores the name.
- The SQL analyzer's regex table reader. It is the second extraction site, and
  it drops the schema the same way.

`llamaindex-spec-rag`:

- The evaluation repository's object-key function.
- The analysis merge module's SQL object name normalizer. This one drives
  Database Invocation identity, so it is the copy that merges a qualified name
  with a bare one. It calls the bare-key function, and it keeps that merge. The
  C# side writes no schema, so the merge states a fact about the caller rather
  than a defect.
- The context builder's stored-procedure name core.
- The path selection module's object leaf.

Two modules change their imports but keep their own logic. The SQL cache store
today imports a private name across a module boundary. The migration report
composes two of the stored-procedure-side functions.

### What each call site holds

Most sites call the bare-key function and keep a string. They pass a string in
and read a string out, exactly as they do today.

Five call sites hold the value instead. Each of these composes a qualified name
today and discards the schema on the next line:

- The stored-procedure fetcher's qualified node name.
- The execution path builder's qualified node name.
- The execution path builder's qualified invocation name.
- The analysis service's schema-aware splitter.
- The SQL execution graph builder's schema-aware splitter.

The schema is already in hand at all five. Holding the value changes no answer
in Step 1, and Step 2b then reads a field instead of parsing a string again.

The two splitters take a default-schema argument today. The module does not.
In Step 1 each of their call sites applies `dbo` itself, with one comment naming
the step that removes it. The default therefore never enters the module.

Two more sites call the analysis service's splitter and keep a hard `dbo` of
their own. Neither site sits in the sixteen-site list or the nineteen-site list.
Both serve path evidence.

- The cached object lookup matches a graph node to the cache object that holds
  its definition. The graph builder creates stored-procedure, view, and function
  nodes from the listing only. This site is therefore not a bare-name lookup.
  The listing commit removes both of its `dbo` fallbacks. After that commit, the
  site compares the schema and the name of the node with those of the object
  exactly. An empty schema on either side matches nothing, and the path reports
  `stale_path`.
- The graph object lookup resolves a function reference on an operation node to
  a function node. The analyzer commit changes this site, because each function
  reference becomes an object with four named fields. The site then reads the
  schema field and the name field and splits no string. An unstated schema takes
  `dbo` at this call site. A comment names Step 2b as the step that removes it.
- After Step 2b, the graph object lookup obeys the two-bucket rule. A reference
  that states a schema matches by full key. A reference that states no schema
  matches every function node with that bare name. Those nodes come from the
  listing, so none carries the Unproven Schema mark. T-SQL requires a schema on
  a call to a scalar user-defined function. An unqualified function reference is
  almost always a built-in function, and it matches no node.
- A function reference that states a Database other than the cache's own matches
  no node. The cache holds no definition of that object, so a local definition
  would be false evidence. The graph builder's function-reference resolution
  obeys the same rules, in the same commits.

### The behaviour change in Step 1

Nine sites fold case with `lower` today and the rest use `casefold`. The merge
moves every site to `casefold`. The two differ only on characters outside ASCII.
No name in the five current caches contains such a character, so no answer
changes in practice.

This is the one intended behaviour change in Step 1. Every other site keeps its
exact behaviour.

### The SQL Cache Identity module

One preparatory issue runs after the test fixture and before Step 1. It makes
the SQL Cache Identity the only way to name a SQL cache. It changes no answer.

Nine sites in the cache store hold that identity as loose strings today, and
each one re-derives it. Step 2a removes the schema part, so without this issue
that removal is an enumeration this spec has to get right. With it, the removal
is one edit in one value type.

- Every public function of the cache store takes a SQL Cache Identity. The cache
  reader, the saved-at reader, the presence check, and the whole-database dump
  all lose their loose database, schema, and server arguments.
- A caller that knows no server gets one from a separately named module
  function. That function reads the cache directory, and it returns nothing when
  no cache names that Database and when two servers both hold it. The identity's
  own constructor stays pure and never reads the disk. The two have different
  error modes, so they do not share a name.
- The branch between the two lives at each call site, not inside one function
  that takes an optional server. Seven sites reach the reader with a server that
  may be empty; each now states which of the two it is asking for. An optional
  server argument is the shallow interface this issue exists to remove, and
  moving it up one layer would keep it.
- The ambiguous-server case becomes a returned value. Today it is observable
  only as a reader returning nothing, so no test can name it.
- The identity's `dbo` default is removed here. Removing a default changes no
  computed filename, and it makes Step 2a's deletion of the field mechanical:
  a site this work misses raises instead of reading `dbo`.
- The identity owns its three filenames: the data file, the Scan Record, and the
  Object Location Index. Nothing outside the cache store composes or filters
  those three suffixes.
- One function lists the cache directory, and it becomes the module's only
  reader of that directory. It returns one row per candidate file: the data
  file's path, and the identity that names it. The two sibling suffixes produce
  no row. A file whose name states no identity produces a row whose identity is
  empty, so a caller that repairs files and a caller that lists them differ only
  in what they do with that row. Rows come back in filename order, and the cache
  listing keeps its own final sort.
- That function decides an identity by a round trip. It parses the stem, builds
  an identity, and composes that identity's own data filename. The row carries
  the identity only when that composed name is the file's own name. Neither the
  parse nor the round trip rejects a sibling file on its own: an index file's
  stem parses into a schema ending in `.index`, and that identity composes back
  to the index file's exact name. The suffix exclusion is what rejects it, and
  it lives in this one function.
- The reverse parse joins the forward compose. One function turns a filename
  stem back into an identity, and it returns nothing for a stem that names none.
  It is the module's only reverse parse, and after this issue the directory
  listing is its only caller.
- The in-memory cache is keyed by the identity rather than by the identity's key
  string. The eviction message then reads fields instead of parsing that string
  back. Nothing inside the module reverse-parses any more.
- The meta writer loses its path argument. The identity already decides that
  path, and the one caller outside the module computed it from the identity
  before passing it in.
- The cache listing still lists a file whose name states no identity. Its row
  carries an identity when the file has one, and the filename stem when it does
  not. `/scan_records` reports exactly the fields it reports today. A file
  nobody recognises stays visible to an operator rather than being dropped in
  silence.
- The listing keeps preferring the Scan Record's own identity fields over the
  filename, and it takes those fields as written. Passing them through the
  identity constructor would raise on a hand-edited Scan Record, which turns one
  visible row into a failed endpoint.
- The graph repair tool stops keeping its own copy of the suffix list. It holds
  two of the three suffixes today, so it treats an Object Location Index as a
  cache file. An index file sorts before its own data file, and an index
  payload's table entries are strings rather than objects, so the first file of
  a repair run raises and the run ends before it repairs anything. The dry run
  hides this, because it returns before the rebuild. Step 2a's recovery plan is
  one repair run, so this is fixed well before Step 2a needs it.
- The repair tool asks the directory listing which files are caches. It loses its
  own cache-root argument, and its cache-root option sets the root the whole
  module reads, the way the index backfill tool's option already does. A row
  whose identity is empty is reported and skipped, under the name the backfill
  tool already prints for an unrecognised identity. The check that rejects a
  payload that is not an object stays, because a name that parses does not prove
  a payload that reads.
- The dry run still returns before the rebuild, and a failed rebuild still ends
  the run. Both paths now select files the same way, and the selection is where
  this defect sat. A rebuild that fails on a file the listing accepted is a
  defect rather than a file to skip, and a repeated run repairs only what the
  earlier run left.
- The server reverse-derivation reads the same directory listing. It is the
  module's third reader of that directory today, and the Scan Record filter it
  carries cannot match any name the pattern it globs can produce.
- The server reverse-derivation matches each listing row on the Database field
  of the row's identity. It never composes a filename suffix. Today it composes
  a suffix from the Database and the schema. A suffix of that shape matches no
  two-part filename, so `/find_by_sp` and `/find_by_table`, which carry no
  server, would find no cache after Step 2a. A match on the identity's field
  has no filename shape to go stale.
- The reverse parse is a method of the identity, beside the forward compose.
  Step 2a changes the number of filename parts. The compose and the parse then
  change in one edit, and neither can keep the other's old shape.
- Two callers outside the cache store move onto the identity in this issue. The
  data status tool calls the presence check with a stated `dbo`. The object
  location lookup builds an identity from each cache listing row. Neither caller
  changes an answer here. Step 2a removes the schema from both, under "One SQL
  cache holds one Database".
- The one-off key-migration tool is deleted, with its test and its two manual
  entries. It migrates a legacy key to a three-part filename, and Step 2a makes
  that filename two parts, so it would migrate to a name no reader recognises.
  Its migration has already run, and Step 2a invalidates every cache regardless.
- `llamaindex-spec-rag` gets no mirror of this value type. That repository
  computes a cache filename and never writes one.

### One SQL cache holds one Database

- One cache covers one Database and every schema inside it. The alternative —
  one cache per schema — was rejected because the cache format cannot record
  which schema an object belongs to, so a cross-schema reference in the SQL
  Execution Graph has no cache that can resolve it.
- The SQL Cache Identity drops its schema part. It becomes server and database.
  The cache filename follows.
- The refresh CLI loses its schema option. A refresh covers the whole Database
  or fails.
- The `db_schema` field leaves the refresh request, the refresh response, and
  the scan record shape. The orchestration client and the refresh CLI in
  `llamaindex-spec-rag` change with it.
- The cache reader and the saved-at reader take a SQL Cache Identity after the
  preparatory identity issue. They lose the schema when the identity loses it.
  That issue already removes the `dbo` default both readers carry today.
- The identity commit starts from the code the preparatory identity issue
  leaves behind, not from the code today. After that issue, every cache-store
  function takes an identity, and no function defaults a schema. The commit
  deletes the identity's schema field. Each site below reads that field, or
  writes a schema field of its own, and the commit changes all of them:
  - The identity's schema field, its filename compose, and its reverse parse.
    The compose and the parse change in one edit, because they sit side by
    side.
  - The meta writer's `schema` field. The loader's comparison of that field.
    The cache-wide `schema` field on the payload is not in this list. The
    listing commit deletes it, under "The schema field on the payload".
  - The Object Location Index's schema field, the index payload's `schema`
    field, and the index loader's comparison of that field.
  - The cache listing row's schema field, and the listing's sort key.
  - The `db_schema` field on the `/scan_records` response.
  - The index backfill tool's report field for the schema.
  - The data status tool's presence check.
  - The loop in the object location lookup that builds an identity from each
    cache listing row.
  - The refresh entry point in the analysis service. It loses its schema
    parameter, and its response loses `db_schema`, with the refresh request.
- The identity commit has a grep check. After the commit, a search of the
  service code and the tool code for a schema read from an identity or from a
  cache listing row returns nothing. The list above names each site. The check
  finds a site the list misses. A missed site raises `AttributeError` only when
  code reaches it, and the data status tool has no test that reaches it.
- Three object location tests state two caches for one Database, one per
  schema. After the identity commit, one Database has one cache, so those
  three tests describe a state that cannot occur. The identity commit deletes
  them. The object location lookup still merges its rows by server and
  Database. That merge becomes dead code, but it gives no wrong answer. Issue 7
  rewrites the located-database shape, and it removes the merge there.
- The SQL cache format version increases. Every existing cache invalidates. No
  migration tool is written, because the data a migration would need — each
  object's schema — does not exist in the old caches.

### The refresh

- The schema filter leaves the object listing. The listing selects the schema
  alongside the name.
- Each object in the cache carries its own schema.
- These schemas are excluded: `sys`, `INFORMATION_SCHEMA`, `guest`, and any
  schema whose name begins with `db_`. The list is a constant, not a setting. It
  is fixed by SQL Server, so it does not grow with the number of Databases.
- The listing reads catalog views that hold no object in `sys` or
  `INFORMATION_SCHEMA`. The list keeps both names anyway, because it describes
  SQL Server and not one catalog view. A change of catalog view then needs no
  change to the list. Today only `guest` and the `db_` rule can exclude an
  object, and Seam 2 tests those two alone.
- Objects already present in `dbo` are untouched by this exclusion. The 175 tool
  procedures currently in the `PUR` cache stay where they are.

### The object listing

Four listing methods exist today. They differ only in a catalog view name and a
column name. Each one filters the schema with an equality test. Each one returns
a bare name inside a list of strings.

- One listing method replaces all four. A kind table drives it. That table names
  the catalog view, the name column, and any extra condition for one kind.
- The method returns rows of three fields: kind, schema, and bare name. It
  returns a named tuple, not a qualified string. A qualified string can carry a
  schema, but every reader must then split it again, and this spec exists to
  stop a caller from re-deriving a name rule.
- The method runs one query. It joins the four selects with `UNION ALL` inside a
  subquery. That subquery gives the schema column one name for all four kinds.
- The query applies no excluded-schema condition. The listing method applies the
  rule once, to the rows the query returns. A rule inside the query text is
  visible to a fake cursor only as a string, and a rule over the returned rows
  is visible as an outcome.
- The comparison ignores case. The SQL comparison it replaces followed the
  Database collation, and the default collation ignores case. This move
  therefore changes no excluded schema.
- The `db_` rule is a prefix comparison, not a SQL `LIKE` pattern. It has no
  wildcard, so it needs no escape. A schema named `dbXyz` stays in the listing.
- The excluded rows travel from the server before the method drops them. Those
  rows are few, so the cost is small.
- The kind values are the names the cache payload already uses: `procedures`,
  `views`, `functions`, and `tables`. The caller groups the rows by kind and
  needs no mapping table.
- The query orders rows by kind, schema, and name. The order inside one kind
  stays stable. The four progress bars keep their current order, because a fixed
  list in the caller decides that order, not the query.
- The progress stage names do not change. No reader compares a stage name
  against a literal, so those names are a display label and not a contract.
- The native dependency dictionary method has the same shape as the four listing
  methods, and this spec leaves it alone. It has no caller in this repository,
  and the `retire-legacy-dependency-dictionary` precondition removes its
  readers.
- The full-database dump loses its schema argument. That argument selects
  nothing once the listing stops filtering, so it would only name a scope the
  dump no longer has.
- Two callers outside the refresh read the procedure listing today. The batch
  analysis entry point and the interactive menu both take bare names. Both move
  to the new listing method. The menu prints `schema.name`, and it passes the
  chosen schema on. A bare name in a menu cannot tell two schemas apart.
- No compatibility wrapper keeps the old bare-name listing alive. A wrapper is
  one more site that drops a schema, and that is the defect this spec removes.

### The per-object fetches

- Each per-object fetch takes the schema the listing reports for that object.
  Every one of these fetches already accepts a schema argument.
- Three sites compose a qualified name into a string instead of binding a
  parameter. All three use one helper. The helper wraps each part in brackets,
  and it doubles a closing bracket inside a part.
- One of those three sites returns nothing when the name does not resolve, and
  its caller then stores an empty definition. That silent empty definition is
  why the helper covers all three sites and not only the one site under review.

### The schema field on the payload

- Each object entry in the cache payload gains a `schema` field. Every object
  carries it, including an object in `dbo`.
- The listing commit deletes the cache-wide `schema` field. The dump stops
  writing that field, because the dump no longer knows one schema. The cache
  store does not write it either. A write from the SQL Cache Identity would
  live for one commit only, because the identity commit removes the identity's
  schema.
- The same commit deletes the three readers of that field. The payload field
  and the meta field are two different fields. The listing commit owns the
  payload field, and the identity commit owns the meta field:
  - The cache validity check's comparison of the cache-wide `schema` field.
  - The SQL Execution Graph builder's fallback rule, described below.
  - The SP Catalog's default schema, described under "The SP Catalog".
- The cache payload builder in the test fixture stops writing a cache-wide
  `schema` key in the same commit. No existing test reads that key, and every
  test payload states `dbo` there, so no answer changes.
- The SQL Execution Graph builder reads each object's own `schema` field first.
  When that field is absent, it reads the object as `dbo`. It does not read the
  cache-wide field. An old cache holds no per-object field and no other schema
  than `dbo`, so this gives the answer the old rule gave. Without this change
  the builder marks a `COMMON` object as `dbo`, and one cache file then states
  two different schemas for one object.
- The graph format version does not increase with the listing change. It rises
  with the analyzer host change instead, because that change alters the graph
  payload. The rule that raised it once per effort is replaced under "The
  Execution Graph payload".
- The SQL cache format version does not increase with the listing change. An old
  cache holds no per-object `schema` field, so the fallback above reads it as
  `dbo`, which is what an old cache holds. A version rise here empties the answer
  for five Databases and buys no correctness. Step 2a raises it, beside the
  identity change that makes an old cache genuinely wrong.
- The dump records a `name_collisions` entry when one kind holds the same bare
  name in two schemas. Nothing reads that entry yet. It exists because the Step
  2a gate asks a person to open one cache file, and because the size of the
  collision problem is unmeasured. Step 2b removes the problem, and this entry
  measures it first.

### The analyzer host

- The SQL analyzer's object-name reader uses the named ScriptDom identifier
  properties for server, database, schema, and base name. It stops slicing the
  last two entries off an identifier list.
- The identifier list omits a part the reference does not state. A two-entry
  list therefore means either `database..name` or `schema.name`, and position
  alone cannot tell the two apart. That is why `WorkTable` and `Common` read as
  schemas today.
- A reference with no schema returns an empty schema. The reader stops
  substituting `dbo`.
- The reader drops its textual fallback. Every caller passes a real object-name
  fragment, so an unexpected shape returns four empty parts instead of a name
  split on dots.
- An unrecognised module reports an empty schema. The host states `dbo` nowhere.
- The analysed module's own identity keeps three fields and gains no database. A
  module cannot name the Database that holds it, so the read side fills that
  part from the SQL Cache Identity.
- Four reference fields carry the four parts: read tables, write tables, call
  targets, and function references. Each entry becomes an object with a server,
  a database, a schema, and a bare name.
- All four parts are always present. An unstated part is an empty string. A key
  that appears only sometimes makes every reader restate the rule, and this work
  exists to end that.
- A function-call reference carries the same four parts. The call target's
  identifiers fill server, database, and schema from the right. The function
  name fills the bare name.
- Duplicate removal and read-minus-write removal compare all four parts. A
  reference that states a database no longer equals one that states none. The
  host reads syntax only, so it cannot know that the two name one table. The
  result over-reports one read, which ADR-0012 already prefers to a lost one.
- The analyzer's JSON contract version increases by one. That version is one
  constant written in two files, one in the host and one in the Python client.
  Both change in the same commit, and a test asserts that the two agree.
- The SQL cache format version does not rise with this change. Only the graph
  format version does.

### The Execution Graph payload

- The four parts reach the persisted graph two ways. Each operation node already
  records the analyzer's own fields as they arrive. Each reads, writes, and
  calls relationship gains the database and the server its reference stated.
- A referenced node gains neither. Node identity holds a type, a schema, and a
  bare name, so two references that disagree share one node. A database written
  on that node would keep one reference's answer and drop the other's.
- A relationship omits the field when the reference stated nothing. That follows
  the optional-field convention the relationship shape already uses.
- The database is recorded as stated. The language rule that reads an unstated
  database as the cache's own Database belongs to the read side, which knows the
  SQL Cache Identity. Filling it here would erase the fact that nothing was
  stated.
- An unstated schema is filled at each call site with `dbo`, and a comment at
  each site names Step 2b as the step that removes it. The analyzer commit
  writes `dbo` directly. It does not read the cache-wide `schema` field, because
  the listing commit deletes that field, and the call sites would then change
  twice. Each of the five caches on disk, and each test payload, states `dbo`
  there today, so the filled value does not change. A reference that states no
  schema therefore keeps matching the node the listing built, exactly as it
  does today.
- A reference that states a database and no schema changes node. It stops
  reading its database as a schema, and it joins the node its bare name and
  filled schema already name. That is the defect this work removes, not a side
  effect of removing it.
- The graph format version rises. Every graph on disk is rejected until it is
  rebuilt.
- One repair tool rebuilds a graph in place, from the definitions the cache
  already holds. It reaches no SQL Server. The existing repair tool already
  works this way and does not read the old version number, so it is extended
  rather than copied.
- No rebuild runs on the load path. That path is the query fast path, and
  rebuilding one large Database's graph runs the analyzer host once per module.
  A rebuild hidden there would block one question for minutes with no progress
  to show.
- The repair tool does not rewrite the Object Location Index. That index holds
  bare names, and no bare name enters or leaves it through this change.
- The graph format version rises whenever the graph payload shape changes. The
  rule it replaces raised that version once per effort, and assumed an
  intermediate shape never reaches a file. Here an operator writes this shape to
  disk and reads it until Step 2b lands.

### The two-bucket lookup rule

Two catalogs answer "does this name exist here?". The SP Catalog answers it for
the C# analysis gateway during a refresh. The Object Location Index answers it
for `/locate_object` during a query. They share no code and they must not
disagree.

One rule governs both, and `CONTEXT.md` carries it:

- A name that states no schema is asked of the bare bucket.
- A name that states a schema is asked of the full bucket.
- A name that states a schema and misses the full bucket falls back to the bare
  bucket. That is a match, and it carries an **Unproven Schema** mark.
- Neither catalog ever substitutes `dbo` for an unstated schema.

The rule lives in prose, not in a shared module. The two catalogs differ in
everything else. The index persists to disk, carries a format version, obeys a
staleness contract under ADR-0012, is keyed by SQL Cache Identity, and covers
two kinds. The SP Catalog lives in memory for one request, is keyed by database
name, and covers stored procedures only. A module holding only the set
arithmetic would need an interface wider than either implementation, and
deleting it would move complexity rather than concentrate it.

Both catalogs compose their keys with the Canonical Object Identity module's
bare-key and full-key functions. That is the part that can silently drift, and
that part is shared.

A third site obeys the same rule. The table match inside `/find_by_table`
compares the targets of an Execution Path with the table that the caller names.
It shares no code with either catalog, and it composes its keys with the same
two module functions. "The table match" states how it applies the rule.

### The SP Catalog

This change belongs to Step 2a, not Step 2b. The catalog is built from a loaded
SQL cache, and it reads the cache-wide schema field that Step 2a deletes. The
listing commit deletes that field, so the catalog changes in the listing commit.

- The catalog's construction drops its default-schema argument. A procedure name
  that states no schema enters the bare bucket only.
- The gateway keeps asking with the schema it read from the C# call site. Under
  the fallback above, a qualified call still matches a catalog entry that states
  no schema, so no match that exists today is lost.
- A match reached through that fallback keeps its Evidence Status of `proven`.
  Only its reason changes, to one that names the Unproven Schema. A downgrade to
  `likely` is rejected: two downstream readers treat `likely` differently from
  `proven`, so a schema distinction would silently change a path decision.

### The read side

- The Object Location Index gains a second bucket per kind. One bucket holds
  bare keys and one holds full keys. The over-report-never-under-report rule is
  unchanged, and the bare bucket keeps every name it holds today.
- A full key has three parts: database, schema, and bare name.
- An object listed in the cache takes the cache's own Database for its database
  part. A graph node takes the database the reference states.
- A graph node that states no database takes the cache's own Database. This is a
  language rule, not a guess: a name written inside a stored procedure with no
  database names that Database. A graph node that states no schema gets no such
  fill, because a default schema depends on the connecting identity and is not
  fixed to `dbo`.
- The located-database row keeps naming the cache it came from. Its server and
  database fields are the cache's SQL Cache Identity, exactly as today. The
  caller intersects on those two fields, so a row that renamed itself after the
  matched key would drop the cache that holds the evidence — an under-report
  that ADR-0012 forbids.
- The row gains a schema field describing the matched key. One Database with
  three schemas produces three rows. The caller's intersection collapses them,
  so extra rows cost bandwidth and never change the Candidate Database Set.
- The row gains one more field when the matched full key states a database other
  than the cache's own. That field is `stated_database`, and it carries that
  database's name. It is absent otherwise. A boolean would force the caller to
  open the cache, which is the one thing `/locate_object` exists to avoid.
- The Declared Database Dependency comparison continues to read server and
  database only.

### The table match

`/find_by_table` matches an Execution Path to the table that the caller names.
Today it cuts both names down to the bare name, so `dbo.AVM` matches
`COMMON.AVM`. Stories 1 and 2 fail at this comparison, not at the index.

- Each Execution Path gains two fields, `read_full_keys` and `write_full_keys`.
  Each element is one full key with three named fields: `database`, `schema`,
  and `name`. No element is a string, so no reader splits one.
- The database part comes from the relationship, because node identity holds no
  database. A relationship that states no database takes the graph's own
  Database. That is the language rule under "The read side".
- The schema part comes from the node. A node that states no schema keeps an
  empty schema.
- The `reads` and `writes` fields keep their strings. The consumer reads them as
  text, and this change does not touch them.
- A caller name that states no database takes the Database of the request. The
  match then compares all three parts.
- A target that states the caller's schema matches. A target that states a
  different schema never matches.
- A target with an empty schema falls back to the bare key. That is a match, and
  the record gains the `unproven_schema` value in its `risk_flags`. The mark
  sits on the record, not on the path: one path serves every table question in
  its scope, and a match on another of its targets carries no mark.
- A caller name that states no schema matches every target with that bare name
  and database. A target whose schema is proven carries no mark. The mark
  describes the target, never the question.
- The record's `table` field carries the matched target as the graph stores it,
  as it does today. A target with an empty schema therefore reports a bare name.
  A schema that the caller supplied never appears as evidence.
- The record gains `stated_database` when the matched key names a Database other
  than the cache's own. It is absent otherwise. The located-database row uses
  the same field under the same rule.
- An Evidence Status stays `proven` when only the schema is unproven, as "The SP
  Catalog" states. A `write_only=True` answer therefore keeps a proven write
  that carries the mark.
- A table that a path reaches through a View or a Function obeys the same rule.
  The lineage index keys its tables by full key. It takes the database from the
  relationship inside the View or the Function.
- After Step 2b no site in the graph query module discards a schema. The match
  uses the full key, the fallback uses the bare key, and both come from the
  Canonical Object Identity module.
- One target with an empty schema produces one Execution Path. It never produces
  one path per candidate schema, and the `path_id` formula does not change.
  Three sites read `path_id` as the identity of one path: the ADR-0016
  deduplication, the merge in `llamaindex-spec-rag`, and `/path_evidence`.
  ADR-0035 records the decision.

### The index states its own format version

The index borrows the SQL cache format version today. Step 2b changes the index
shape and not the cache shape, so it has no version to raise. A one-bucket index
then reads as fresh, a full-key question misses, and the caller skips a cache
unopened. That is the authoritative under-report ADR-0012 forbids and story 46
promises to prevent.

- One constant per persisted shape. The cache keeps its format version, and the
  index gains one of its own. The constant sits beside the cache's in the cache
  store, and its name matches the index file suffix that module already owns.
- The constant is `_INDEX_VERSION` and the payload field is `index_version`. The
  cache's pair is `_SQL_CACHE_VERSION` and `cache_version`. The two pairs share
  one word-shape, so the root word alone tells a reader which file a version
  describes. An adjective such as `format` appears in neither pair.
- The index payload drops the cache format version field. A cache whose format
  version rose is unreadable, so the Database it names answers nothing whether
  the index prunes it or not. An operator refresh then rewrites the data file,
  and the modification-time rule ages the index out on its own. The field bought
  no guarantee that those two rules do not already hold.
- The index value type drops its version field with it. The builder filled that
  field with the constant, the loader filled it with the same constant, and
  nothing else read it. The version is a property of the file, not of the index
  content.
- The version starts at 1. An index written before this change carries no version
  field at all, so every index on disk counts as absent the day Step 2b deploys.
- The loader compares the stated version for exact equality. A version it does
  not recognise counts as absent, older or newer. A newer one reaches disk when a
  deployment is rolled back, and a reader must not trust a shape it cannot read.
- An index missing a bucket is absent, not an index holding an empty bucket. The
  loader cannot know which bucket a reader will ask for, because the kind arrives
  at the reader and not at the loader. It therefore requires all four buckets,
  each a list. The whole staleness rule stays inside the one function that
  defines it today.
- Each of the four buckets states which key it holds: a bare bucket and a full
  bucket for stored procedures, and a bare bucket and a full bucket for tables.
  The bare bucket does not reuse today's field name. That one name would then
  mean every name the cache holds in a file written before Step 2b, and the bare
  keys in one written after. A person reading a file by hand has no version check
  in front of them.
- Step 2a raises no index version. The identity loses its schema there, the index
  filename changes with it, and an index written before Step 2a is never found.
  Those orphaned index files stay on disk beside the orphaned cache data files.
  Story 18 already rules out a migration tool, and a file nobody reads does not
  earn a cleanup step of its own.
- The version rise degrades every Database to `unindexed` until the indexes are
  rebuilt. The backfill tool rebuilds them from the caches already on this
  machine and opens no SQL Server connection, so Step 2b needs no second operator
  refresh.
- Four written statements about the index go stale on the day Step 2b deploys.
  This issue corrects all four. The tool's module docstring calls the tool a
  one-off migration. Its all-caches function states that the index has no version
  of its own. The operator manual states that a later rerun is never needed. The
  advanced manual's tool table states the same. Each states instead that a rerun
  is the recovery path after an index version rise.
- The two manual sentences that list the degrade reasons stay as they are. Each
  says an index counts as absent when a version does not match. That sentence
  stays true under the new rule, and it names no version owner.
- The backfill tool opens no index file and compares no version. It rebuilds
  every index and overwrites the old one, exactly as it does today. A tool that
  reported "this index held the old version" would carry a second copy of the
  staleness rule, and that rule stays inside the one function that owns it. A
  lost index returns on the next run, so it earns no report of its own.

### Cross-repository coordination

- `llamaindex-spec-rag` gets its own module, not a shared package. The module
  mirrors this repository's: the same value type, the same parse function, and
  the same two key functions. Its four call sites all use it.
- That module sits in the orchestration package. The evaluation code already
  imports that package from six files, so the fourth call site needs no new
  top-level package.
- One fixture file carries the whole cross-repository agreement. It is checked
  into this repository, under the test directory, as JSON. One file cannot drift
  from itself, so no copy needs comparing.
- The file holds two case lists. The `object_names` list covers the Canonical
  Object Identity rule. The `sql_cache_identity` list covers the SQL Cache
  Identity rule.
- Each `object_names` case states an input name, the three parsed parts, the
  bare key, and the full key. The case states the parsed parts because the parse
  function returns an empty schema, and a key column alone cannot show that.
- Each `sql_cache_identity` case states a written server, a database, a schema,
  and the cache filename. The case ends at the filename. The file-name safety
  rule that both repositories copy is therefore covered by the same list.
- `llamaindex-spec-rag` reads the file by relative path, the way that
  repository's cache-identity test already reaches across. A missing file fails
  the test. A skipped test is not an agreement, and a skip is the operator state
  this work removes.
- The `llamaindex-spec-rag` copy of the server rule gains the two rules it
  lacks. It strips a `tcp:` prefix and a `,port` suffix, as this repository's
  copy already does. This repository writes the cache files, so its copy is the
  one that holds. No existing cache filename changes, because a plain host name
  already normalizes the same way under both copies.
- Nothing reads the cache directory to prove the agreement. The test that
  compared a computed filename against a file on disk is deleted. That test
  skipped whenever the sibling checkout held no cache. It also stated only plain
  host names, so it never reached the drifted server rule.
- The evaluation repository keeps one reader of the cache directory. It holds
  two today: one excludes both sibling suffixes, and one excludes the Scan
  Record alone. The second calls the first instead of holding its own list, and
  that function takes a name stating that it returns data files. Its two
  failures — a directory that does not exist, and a directory holding no
  cache — already read the same in both readers, so no caller's behaviour
  changes. The
  repository's own case for that reader gains an index file beside the data
  file; the case already states that a Scan Record is ignored, and its name
  gains the second kind.
- The evaluation code reads the cache directory directly and derives its cache
  identifier from the filename. The filename change alters every identifier. No
  compatibility layer is added; the routing expectations are regenerated, which
  is what the identifier exists to force.

### Documents

- A new ADR records the decision that one SQL cache holds one Database, and why
  the per-schema alternative was rejected. The number is 0033. The last existing
  record is 0030. Each of the two specs named under Preconditions takes one
  earlier number, and this record must not collide with either.
- `CONTEXT.md` gains a Canonical Object Identity entry. That entry also carries
  the two-bucket lookup rule, because two catalogs obey it and share no code.
- `CONTEXT.md` gains an Unproven Schema entry. One term covers both places the
  concept appears: the mark on an Execution Path, and the catalog match reason.
  The entry names `unproven_schema`, the value that carries the mark in the
  `risk_flags` of a table match record.
- The `CONTEXT.md` SQL Cache Identity entry is corrected to a two-part identity.
- The `CONTEXT.md` SQL Cache Identity entry also records that the identity owns
  its three filenames, that nothing else composes or filters them, and that the
  cache store alone answers which files in that directory are caches. The
  filtering half is the half that broke, so it is stated rather than implied.
  This is a separate sentence from the two-part correction, and it lands in the
  preparatory issue rather than at Step 2a.
- A second new ADR records that the Object Location Index states its own format
  version, and that an incomplete index is absent. Its number is 0034, after the
  0033 above. Its title is "The Object Location Index States Its Own Format
  Version; an Incomplete One Is Absent".
- ADR-0012 gains an `Amended by ADR 0034` note, in the form ADR-0004 already
  uses. Its Decision paragraph names a different cache format version as a
  degrade reason, and that reason stops existing.
- A third new ADR records that an unproven schema marks one Execution Path and
  does not multiply it. Its number is 0035, after the 0034 above. Its title is
  "An Unproven Schema Marks One Execution Path; It Does Not Multiply It".
- ADR-0035 states that neither ADR-0015 nor ADR-0016 requires one path per
  candidate schema, and that story 7 once read them that way. It states that one
  unknown schema would become several facts of which at most one is true. It
  states that a path holds many targets, so one path per candidate schema
  multiplies into a cartesian product.
- ADR-0035 records two rejected alternatives. The first puts the candidate
  schema inside the `path_id` identity, which changes every `path_id`. The
  second adds a table part to the ADR-0016 deduplication key, which leaves the
  merge in `llamaindex-spec-rag` and `/path_evidence` reading two paths as one.
- ADR-0015 and ADR-0016 gain no note. Neither decision changes, and an `Amended
  by` note in this repository states that a decision changed.
- The `CONTEXT.md` Object Location Index entry is corrected. It states today that
  an index disagreeing with the version of the cache it describes counts as
  absent. It states instead that an index whose own format version is not the one
  this build writes counts as absent, and it points at ADR-0034.
- That one correction lands with the version rise at Step 2b, not with the
  documents issue. The sentence it replaces turns wrong the moment the constant
  rises, and every agent reads `CONTEXT.md` before it reads anything else.
- `CONTEXT.md` gains a test fixture entry. It records that one module is the
  only source of a cache payload, a format version, and an analyzer operation in
  a test. It names the check that enforces this rule.
- The cache store docstring that states schemas collapse to one key is
  corrected.
- A sentence in the operator manual or the advanced manual belongs to the issue
  that changes the behaviour it describes. It does not wait for the documents
  issue. This is a rule rather than a list, because this spec changes more
  behaviours than a hand-kept list of sentences survives.
- The documents issue therefore holds the new records alone: the three new ADRs,
  the note on ADR-0012, and the `CONTEXT.md` entries that no single behaviour
  change owns.
- Two manual sentences outside the index work follow the rule above. One advanced
  manual example sends the request field Step 2a removes, so it belongs to issue
  5. One advanced manual sentence states that a table comparison strips a `dbo.`
  prefix, and Step 2b stops that stripping, so it belongs to issue 7.

### How the work is split into issues

Eight issues. Each issue changes one repository, so each is accepted inside the
repository it changes.

1. The test fixture in this repository. One cache payload builder, one analyzer
   operation helper, the write helper's identity argument, the legacy-key
   helper, the two version constants, and the check that keeps every shape at
   one source.

   The issue covers twenty-three test files and the fixture module. Seventeen
   files build a payload. Two more hold a stale graph version and no payload.
   Three more hold a contract version and no payload. One more holds an analyzer
   operation and no payload. The check is a new file, and Seam 3's file gains
   the two mismatch cases.

   This issue changes no behaviour, and it touches no module either precondition
   spec deletes. It runs before every other issue, because Seam 1 and Seam 4
   both add cases to the builder.

   The issue lands in five commits, one per shape. "One test fixture module"
   states the order and the proof that behaviour holds.

   Three of the twenty-three files sit on the decompile-wrapper path and hold no
   SQL object name. They join this issue because rule two of the check covers
   the contract version whole or not at all.
2. The SQL Cache Identity in this repository. Every cache-store function takes
   the identity, one function lists the cache directory, the server
   reverse-derivation gets its own name and reads that listing, the reverse
   parse joins the forward compose, the meta writer loses its path argument, the
   in-memory cache is keyed by the identity, the identity's `dbo` default is
   removed, the graph repair tool stops keeping its own suffix list, the index
   backfill tool follows the identity, and the one-off key-migration tool is
   deleted. The server reverse-derivation matches on the identity's Database
   field, and the reverse parse becomes a method of the identity. The data
   status tool and the object location lookup move onto the identity.

   The backfill tool builds an identity from a cache listing row and then asks
   the loader for that cache by database and schema. Both calls lose the schema
   at Step 2a, and no other issue names this tool. Issue 7 cannot accept without
   running it, so it is repaired here.

   This issue changes one behaviour, and it touches no module either precondition
   spec deletes. The one behaviour is the repair run: over the cache directory as
   it stands today it raises on its first file and repairs nothing, and after
   this issue it runs to the end. Every other part of this issue returns what it
   returns today.

   The issue lands in two commits. The first commit adds the directory listing
   and moves the repair tool, the cache listing, and the server
   reverse-derivation onto it. That commit carries the one behaviour change, so
   a revert of it is a revert of that change alone. The second commit spreads the
   identity through the module's interface, moves the backfill tool onto that
   interface, and deletes the key-migration tool. The tool keeps reading the
   cache listing exactly as it reads it today, so the first commit leaves it
   untouched.
   Step 2a's recovery plan needs the first commit, and Step 2a's own edit needs
   the second, so the first can deploy alone but neither commit is optional.

   It runs after the test fixture: that issue already moves seventeen files onto
   one payload builder, so running it first means this issue edits one fixture
   module instead of seventeen test files.

   It waits for the whole of the test-fixture issue, not for that issue's second
   commit. The test-fixture issue proves that behaviour holds by comparing two
   runs of the suite, and a second issue inside that interval voids the proof.

3. Step 1 in this repository. Nineteen sites, the new module, the shared
   cross-repository fixture file, and the precondition check that the two deleted modules are
   gone.

   The fixture carries both case lists. The `sql_cache_identity` list states
   three-part filenames, because the identity still holds a schema until Step
   2a. This repository already applies all four server rules, so both lists pass
   here.

   This issue also lands in two commits. The first commit removes the `dbo`
   default from the sixteen static-analyzer sites listed under "The `dbo`
   default in the static analyzer". It changes no answer. The second commit
   does the nineteen-site merge and the `casefold` change.
4. Step 1 in `llamaindex-spec-rag`. Four sites, the mirror module, the shared
   fixture's second reader, the server rule, and the second cache-directory
   reader.

   That reader answers nothing wrong today: a downstream type guard discards the
   files it wrongly admits. It joins this issue because this issue is the
   earliest one in that repository, and because it is the same defect the
   preparatory issue removes here.

   The `sql_cache_identity` list fails in this repository before the fix. This
   repository's server rule lacks the `tcp:` prefix rule and the `,port` suffix
   rule, and this issue adds both. The same issue deletes the test that compared
   a computed filename against a file on disk.
5. Step 2a in this repository. The object listing, the per-object fetches, the
   identity, the filename, the refresh, the analyzer host, the format version,
   the SP Catalog, and the advanced manual example that sends the removed request
   field. The catalog belongs here because it reads the cache-wide
   schema field this issue deletes.

   This issue lands in three commits. The analyzer commit changes the host, the
   JSON contract version, the graph payload, the graph format version, and the
   repair tool. It also fills an unstated schema with `dbo` at each call site,
   under "The Execution Graph payload". It also changes the graph object lookup
   and the graph builder's function-reference resolution, under "What each call
   site holds". The listing commit collapses the object
   listing and carries a schema on each object; it raises no version. It deletes
   the cache-wide `schema` field and its three readers: the cache validity
   check's comparison, the graph builder's fallback, and the SP Catalog's
   default. It also removes the two `dbo` fallbacks of the cached object
   lookup. Those fallbacks read the schema of each object, not the cache-wide
   field, so they are not among the three readers. It also removes the
   cache-wide key from the fixture's payload
   builder, and it adds the cache store case under "The cache-wide schema
   field, over a temporary cache root". The identity commit changes the
   identity, the filename, the `sql_cache_identity` case list, and the cache
   format version. It also changes every site listed under "One SQL cache holds
   one Database". Those sites include the meta file's `schema` field, the Object
   Location Index's `schema` field, and three object location tests that it
   deletes. The grep check in that section is part of this commit's acceptance.

   Each commit leaves the whole test suite green on its own. Deploying the three
   commits together does not replace this rule. Each commit therefore changes
   the tests that its own change breaks, and its message names each test file it
   changes. A test that fails at one commit and passes at the next fails this
   rule.

   The order matters. The analyzer commit rejects every graph on disk, and one
   local repair run restores all five caches. The listing commit leaves them
   loading. The identity commit stops them loading, and only an operator refresh
   returns them.

   The analyzer commit stands alone. It reaches no SQL Server, it needs nothing
   from the other two, and it can deploy before them. Shipped beside the identity
   commit it stays correct, but the repair tool then has nothing to do: those
   five caches are already invalid for the identity reason, and their
   replacements are born with the new graph shape.
6. Step 2a in `llamaindex-spec-rag`. The removed request field, the refresh CLI,
   the regenerated routing expectations, and this repository's reader of the
   two-part `sql_cache_identity` case list.
7. Step 2b in this repository. The index buckets, the index's own format
   version, the located-database shape, the table match rule, the two full-key
   fields on an Execution Path, the Unproven Schema mark, the bare-key fallback
   of the graph object lookup, every written sentence
   that describes the index, and the advanced manual sentence about the stripped
   `dbo.` prefix.

   The format version lands in the same commit as the buckets. The constant and
   the shape it guards enter version control together.

   The sentences travel in that same commit: the backfill tool's two docstrings,
   the operator manual's rerun advice, the advanced manual's tool table, and the
   `CONTEXT.md` Object Location Index entry. Each turns wrong when the constant
   rises, and issue 8 lands after this one.

   Accepting this issue includes one run of the index backfill tool on this
   machine. The version rise degrades every Database to `unindexed`, and that
   run is what returns the pruning. It reads the caches already on disk and
   reaches no SQL Server, so it is not the operator action under Preconditions.
8. The documents. The three new ADRs, the amendment note on ADR-0012, the
   `CONTEXT.md` entries that no single behaviour change owns, and the cache store
   docstring about collapsed schemas. The Object Location Index entry is not
   here; issue 7 carries it.

Issues 5 and 6 deploy together. Issue 7 is blocked by the operator action named
under Preconditions.

## Testing Decisions

A good test here states an externally visible outcome. It gives a name in and
reads an answer out. It does not assert which function produced the key, how
many buckets the index has, or what a private helper returned.

Four seams. Three already exist. The SQL Cache Identity work adds none.

The `dbo` default removal needs no seam and no new test. An omitted schema
argument now raises `TypeError` at the call site. That is a Python
argument-binding rule, not an externally visible outcome, so this section does
not assert on it directly. The existing test suite still exercises every
updated call site; a site this change misses fails that suite instead of
reading `dbo`.

### The SQL Cache Identity, over a temporary cache root

The preparatory identity issue adds no seam. Its prior art is this repository's
cache store test file, which already points the cache root at a temporary
directory through the shared fixture's cache-root helper.

Three cases join that file. The server reverse-derivation returns nothing when
two servers hold one Database name; today that outcome is observable only as a
reader returning nothing, so no test can name it. The reverse parse returns an
identity for a three-part stem and nothing for a stem that names none; that
second case is Step 2a's safety net, written before Step 2a needs it. The
directory listing over a root holding all three files returns the data file
alone, and it returns an empty identity for a file whose name states none.

One more case covers a Database name that holds the separator `__`. The case
writes a cache for that Database, and the server reverse-derivation then finds
its server. Today that name parses correctly only because the schema is always
the last part. After Step 2a no schema part exists, so this case proves that the
parse and the reverse-derivation still find the cache. Step 2a changes the case
to a two-part filename, and it keeps the assertion.

One more case belongs to the repair tool: a cache directory that holds an Object
Location Index beside its data file repairs the data file and leaves the index
alone. That is the externally visible form of the defect described under "The
SQL Cache Identity module". The case writes that index through the module's own
index builder and index writer. An index payload written by hand is a second
source of a shape, which the test-fixture issue exists to remove, and this
defect turns on what the real payload holds: table entries that are strings.

The repair tool's test file passes a cache root into the tool eight times today.
Those calls move onto the shared fixture's cache-root helper, because the tool
loses that argument.

This issue's contract is the fixture issue's contract, with one stated
exception: every existing test returns the same result before and after it, and
the repair run that could not finish now finishes. The cache store test file holds roughly
forty-seven hand-written filename literals. A literal inside an assertion stays,
because proving the filename rule is that file's own subject. A literal inside
test setup moves to the identity, because it proves nothing there and copies the
rule.

The identity issue also visits the shared cache fixture, but only its meta
write: the fixture holds a second copy of the meta format today, and the meta
writer's new shape is what lets the fixture borrow the real one instead. The
rest of the fixture's interface is already the shape the test-fixture issue
leaves behind.

### The cache-wide schema field, over a temporary cache root

The listing commit adds no seam for this. Prior art is the cache store test
file, which already points the cache root at a temporary directory.

One case joins that file. It saves a payload through the cache store, reads the
saved data file as raw JSON, and asserts that the top level holds no `schema`
key. The identity commit's grep check cannot catch this field: each object entry
also carries a `schema` key, so a text search cannot tell the two keys apart.
Without this case, a new reader can depend on the field again, and nothing
fails.

### The index format version, over a temporary cache root

Step 2b adds no seam for this. Prior art is the cache store test file's existing
group of absent-index cases: a missing file, an unreadable file, an index older
than its cache, and an index moved by hand to another identity. Each names one
reason and asserts that the loader reports no index. The new cases join that
group. What the four buckets answer stays under Seam 1.

- The case that writes a different cache format version into the index is
  rewritten to write a different index format version. The check it asserted
  stops existing; the outcome it asserted does not.
- One new case writes an index payload with no version field at all. That is the
  shape every index on disk has the day Step 2b deploys, and it is the only one
  of these reasons a deployment actually produces.
- One new case removes one bucket from a written index. One case covers the
  rule: the loader treats the four buckets alike, so a case per bucket walks one
  branch four times.
- The case that asserts the index carries its identity loses its assertion on the
  version field, because the value type stops holding one. Its name changes with
  it.
- Each new case sets the index file's modification time ahead of the cache's, as
  the existing version case already does. Otherwise the age rule alone produces
  the same outcome and the case proves nothing.
- One more case belongs to the backfill tool's own test file. It writes an index
  with no version field, it runs the tool, and it asserts that the loader then
  returns an index. That is the path issue 7's acceptance rests on, and no test
  joins those two ends today. The tool's existing rerun case starts from a
  current index, so it proves something else.
- That case builds its starting index the way the group above builds one: the
  writer writes a real index, and the case then edits the file. No test states an
  index payload by hand.

### One test fixture module

Four shapes scatter across the test suite today. A SQL cache payload sits in
seventeen files. A stale graph format version sits in twelve files. A contract
version literal sits in four files. A hand-written analyzer operation sits in
six files. The four sets do not nest, and twenty-three test files hold at least
one shape.

Five files write a payload to disk through the shared fixture's write helper.
Twelve files replace the cache reader with a stub, and that stub returns a
payload the test wrote by hand.

The two groups fail in opposite directions. A payload on disk reaches the real
reader, so a format change rejects the file and the test fails. A stubbed
payload reaches no reader, so a format change leaves the test green against a
shape no cache holds. The second failure is the Step 2a gate's problem one layer
down, and no operator check catches it.

The twelve stale graph versions are that second failure today. No file among
them writes a cache, loads a cache, or touches the in-memory cache. The cache
store rejects a graph whose version differs from the constant. Each of the
twelve escapes that rejection, because no reader ever sees the version it wrote.

One fixture module serves all four shapes. The preparatory issue moves every
hand-built shape onto it, before Step 2a.

- The builder joins the existing shared cache fixture module. That module
  already holds the cache-root helper and the write helper.
- The builder covers the payload envelope and the four object lists. The
  Execution Graph payload keeps its own helper, so the two format versions stay
  on two layers. A test composes a graph with that helper, then passes the graph
  to the builder.
- Two layers, not one. The graph format version and the SQL cache format version
  rise in two different commits, so one builder must not own both payloads.
- The two version constants are a different thing. A test reads a constant and
  never writes one. Owning both constants therefore breaks no layer, and the
  check owns them rather than the builder.
- The builder takes each object as a written name. It parses that name with the
  Canonical Object Identity module. A name that states no schema takes `dbo`,
  because the builder stands in for the object listing, and the listing always
  reports a schema. This is not a comparison-key default, and the builder's
  documentation states the difference. The alternative — the builder splitting
  the name itself — is a twenty-fourth site.
- The builder reads the graph format version from the graph module's constant.
  Every other graph format version in a test reads that constant too.
- The twelve stale values are inherited, not chosen. The discriminator is
  whether anything reads the value. No file among the twelve reaches a reader,
  so each stale value becomes the constant and no answer changes.
- A test that needs a version other than the current one writes that version
  relative to the constant. Prior art is the repair tool's test, which already
  writes one less than the graph constant.
- Every contract version in a test reads the analyzer client's constant. Eight
  literals in four files become that constant. Four literals assert the value,
  and four stubs return it.
- The existing assertion that pins the graph constant to one number stays where
  it is. That assertion's subject is the constant itself.
- The write helper takes a SQL Cache Identity instead of a filename. It writes
  the meta file through the cache store's own meta writer, so the meta format
  stays defined in one place. Today the fixture holds a second copy of that
  format, and that copy reads the cache-wide schema field Step 2a deletes.
- A separate helper, named for the purpose, writes a cache under a key no
  identity can produce. Seven call sites need it. Those sites prove the store
  rejects a key written before the server part existed. A flag on the first
  helper would make a deliberate anomaly look like an option.
- Seven more call sites compose a current cache filename by hand. They move to
  the identity. A hand-written filename is a second copy of the filename rule,
  and it survives Step 2a as a name nobody recognises.
- A test file keeps a local wrapper that names its own intent, as long as that
  wrapper holds no payload key. Two files hold a wrapper identical to the
  other's; that wrapper moves into the fixture module.
- The stubs that replace the cache reader call the builder. The reader loses its
  schema parameter in Step 2a, so each of those stubs fails on its signature
  first. That failure is loud, and it is why every stub gets visited.
- A third helper builds an analyzer operation from a short written name. The
  operation carries the object references, so one helper covers the operation and
  its references. Five files move onto it, and it joins the fixture module beside
  the builder.
- The helper emits today's shape in this issue. The four-part reference arrives
  with Step 2a's analyzer commit, and that commit changes the helper's output
  alone. This issue buys Step 2a one edit in place of five.
- Two test files write an operation out in full and keep doing so. The graph
  builder's test and the analyzer host's test both take that shape as their
  subject, so writing it out is their job.
- One check keeps every shape at one source. The check reads every file under
  the test directory. It holds four named rules. It excludes its own file by
  path, not by a list a reader must maintain.
- Rule one: a payload key literal fails outside the fixture module. The fixture
  module is the only name on this rule's allow list, because a second allowed
  name is a second payload shape.
- Rule two: a graph version or a contract version must read a constant, or an
  expression over a constant. A bare number fails.
- Rule three: a bare number passes when the comparison's other side names the
  constant. That rule reads the shape of the line. No line number and no file
  name enters the check.
- Rule four: an analyzer operation key fails outside the fixture module. This
  rule allows two more names, the graph builder's test and the analyzer host's
  test. Rule one's reason does not apply here. A contract test that writes the
  shape out in full states the contract, and it holds no second shape.
- The check reads the test directory alone. Both constants also live in product
  code, and the C# half of the contract version lives in the host. Seam 3
  asserts that the two contract constants agree, and it covers the half no
  Python check can read.

This issue changes no behaviour. The whole suite returns the same result before
and after it.

One run of the suite records that result before the issue starts. A second run
records it after the issue ends. The two runs compare by test identifier. Every
identifier must report the same outcome, and the two identifier sets must match
exactly. A count of passes and failures hides one test that breaks beside
another that starts passing.

The issue lands in five commits, one per shape. The first commit adds the
builder, the graph helper, the operation helper, the write helper's identity
argument, and the legacy-key helper. It changes no call site. The second commit
moves the payload shape. The third commit moves the two version constants and
adds the mismatch cases. The fourth commit moves the operation shape. The fifth
commit adds the check, which stays red until every earlier commit lands.

This issue owns one shape that this spec's subject does not reach. The contract
version sits in three files on the decompile-wrapper path, and no SQL object
name reaches them. They join this issue because the check covers a rule whole or
not at all. They do not join it because they share this spec's subject.

### Seam 1 — the analysis service over a fixture cache on disk

The highest seam, and the one that covers the most. Prior art is the
locate-object test file and the SQL execution graph test file. Both use the
shared cache-root helper to point the cache root at a temporary directory, write
a cache payload, then call the service function.

This seam covers: multi-schema answers, the schema field on a located Database,
the cross-database field on a located Database, the bare-key and full-key
buckets, the database fill rule for a graph node that states none, the table
match rule, and the guarantee that a Declared Database Dependency match is
unchanged.

The table match rule takes eight cases. Each one writes one cache for the
`Response` Database with a hand-built graph, asks `/find_by_table` for one name,
and reads the records back.

| # | The graph holds | The caller asks | The answer |
|---|---|---|---|
| 1 | `COMMON.AVM` | `dbo.AVM` | No record. |
| 2 | `COMMON.AVM` | `COMMON.AVM` | One record, with no mark. |
| 3 | `AVM`, with no schema | `COMMON.AVM` | One record. Its `table` is `AVM`, it carries `unproven_schema`, its Evidence Status is `proven`, and `write_only=True` keeps it. |
| 4 | `COMMON.AVM` and `dbo.AVM` | `AVM` | Two records, with no mark. |
| 5 | A relationship that states `PUR.dbo.Users` | `Response.dbo.Users` | No record. |
| 6 | A relationship that states `PUR.dbo.Users` | `PUR.dbo.Users` | One record, with `stated_database` equal to `PUR`. |
| 7 | A relationship that states no database, to `dbo.Users` | `Response.dbo.Users` | One record, with no `stated_database`. |
| 8 | One View that reads `AVM`, and one that reads `dbo.AVM` | `COMMON.AVM` | One record for the first View, with the mark. No record for the second. |

No case calls the table match function directly. Its keys are the internal
detail this section rules out asserting.

The SP Catalog is built from a loaded SQL cache, so it sits under this seam too.
A test builds a multi-schema payload and reads the catalog back through the
service function that loads it. No new seam is added for the catalog, because
how the catalog is built is exactly the internal detail this section rules out
asserting.

One existing gateway test already reads the catalog's two buckets directly. It
gains one case: a caller states a schema, the catalog holds the name without
one, and the result is a match carrying the Unproven Schema reason.

The cache payload builder under "One test fixture module" serves this seam. A
multi-schema payload is one call on it. That builder is an addition to an
existing file, not a new seam.

Many existing tests write an analyzer operation by hand, to reach the graph and
path code behind it. One shared helper builds that operation from a short
written name, so those tests keep reading as tests of graph queries and paths. A
test whose subject is the analyzer contract itself writes the shape out in full
instead.

The helper emits today's two-part name in the preparatory issue. Step 2a's
analyzer commit changes it to emit the four parts, and it changes no call site.

Path evidence takes three cases. Each case writes one cache for the `Response`
Database and asks for the evidence of one path.

| # | The graph holds | The answer |
|---|---|---|
| 1 | A path through `COMMON.usp_Load`, whose operation calls `COMMON.fn_Rate()` | The evidence holds both definitions. |
| 2 | A local `dbo.fn_Rate`, and an operation that calls `PUR.dbo.fn_Rate()` | The evidence holds no function. |
| 3 | `COMMON.fn_Rate` and `dbo.fn_Rate`, and an operation whose reference states no schema | The evidence holds both definitions. |

Cases 1 and 2 land with Step 2a. Case 3 lands with Step 2b.

This seam cannot prove that a real refresh produces schemas. It builds its own
payload. The gate under Further Notes exists for that reason.

### Seam 2 — the SQL analyzer over a fake cursor

Prior art is the definition-fetch test file, which injects a fake cursor that
records the query text and returns canned rows.

This seam covers: the listing runs one query, that query selects a schema, and
it applies no schema filter. It also covers the grouping, because one row set
must produce four kinds in the payload.

The excluded-schema rule sits in the listing method, as a filter over the
returned rows. This seam therefore tests the rule as an outcome. The fake cursor
returns rows in `dbo`, `guest`, `db_owner`, `DB_Reports`, and `dbXyz`. The
listing keeps the `dbo` row and the `dbXyz` row alone. The `DB_Reports` row
proves that the comparison ignores case, and the `dbXyz` row proves that the
`db_` rule has no wildcard. A filter in the caller moves the rule out of this
seam's reach, so the filter stays inside the listing method.

### Seam 3 — the StaticAnalyzerHost over real .NET

Prior art is the command-object contract test file, which skips when `dotnet` is
absent and otherwise runs the host for real. This machine has `dotnet`, so this
seam runs here rather than skipping.

This seam covers: a four-part reference keeps its database, a three-part
reference keeps its database and schema, a two-part reference keeps its schema,
and a one-part reference keeps an empty schema. It also covers a reference that
states a database and skips the schema, which is the case that produced the
`WorkTable` and `Common` nodes. It covers the bracket form of each, and it
covers a function-call reference.

This seam also asserts that the two contract version constants agree. The host
reports its version, and the test compares that number against the Python
client's constant. A commit that raises one constant and not the other then
fails here, rather than at the first real analysis run.

This seam's file gains two cases that run no .NET. Each one stubs the host and
returns one more than the client's constant. The client raises the contract
mismatch in two places, and one case covers each. Today no test reaches either
raise, and no test states a version the client must reject.

A real host can never report a version the client rejects, so these two cases
stub. They join this file rather than the file whose subject is decompile
onboarding. A maintainer who raises the constant reads the host's test file.

### Seam 4 — the Canonical Object Identity module over strings

The one new seam. It is justified twice.

First, Step 1's contract is that one behaviour changes and no other. Seam 1 can
only see final answers; it cannot show that twenty-three sites converged on one
rule. Only a test at the rule itself can.

Second, the cross-repository agreement carries a case list for this rule. The
fixture's `object_names` list is this seam's case list. Without this seam that
list has nowhere to live.

This test passes strings in and reads strings out. It builds no graph and opens
no cache. The mirror module in `llamaindex-spec-rag` gets the same seam over the
same fixture file.

The fixture's `sql_cache_identity` list adds no seam. Each repository already
holds a test file for that rule, and both files read the list. This repository
uses its cache store test file. `llamaindex-spec-rag` uses its cache identity
test file, which loses its disk comparison in the same change.

## Out of Scope

- Normalizers for other concepts stay where they are: program file names,
  refresh program paths, file paths in the migration and coverage reports, the
  report's `<unknown>` database sentinel, shared component names, server host
  names, C# method call splitting, and contract identity.
- The grounding module's normalizer in `llamaindex-spec-rag` mixes program file
  names with SQL object names. Program file names are out of scope above, so
  that site stays where it is.
- The server normalization rule keeps two implementations, one per repository.
  No shared package holds it, for the same reason no shared package holds the
  Canonical Object Identity module. The `sql_cache_identity` case list keeps the
  two implementations in agreement, and the rule itself stays where it is.
- The one-off measurement scripts in the evaluation repository's scratch
  directory are not updated.
- The 175 tool procedures in the `PUR` cache are not removed. They are in `dbo`
  and the excluded-schema list does not reach them.
- No shared package is created between the two repositories.
- No mirror of the SQL Cache Identity value type is added to
  `llamaindex-spec-rag`. That repository computes a cache filename and never
  writes one, and the shared fixture's `sql_cache_identity` case list already
  keeps the two rules in agreement. A second value type would be one more shape
  to keep in step, for no second writer.
- No shared module holds the two-bucket set arithmetic. The SP Catalog and the
  Object Location Index keep their own. They share the key functions and the
  written rule, and nothing else.
- No compatibility layer preserves old cache identifiers.
- Linked server names are parsed but not acted on. A four-part reference keeps
  its server part in the analyzer output; no lookup consumes it yet.
- Running any refresh is an operator action on another machine. No issue holds a
  step that runs one.
- The native dependency dictionary method keeps its schema argument and its
  equality filter. It has no caller in this repository.
- The three bare-name lookup dictionaries keep their current keys. They merge
  two schemas that hold one name, and the two-bucket rule under Step 2b is what
  separates them. This spec records that collision and does not fix it early.
- The unqualified function-call rule stays. A function call that states no
  target is still not recorded, and that rule is what keeps built-in functions
  out of the graph. It is not a default-schema defect.
- The common-table-expression exclusion keeps comparing the bare name only. A
  reference that states a schema is still dropped when its bare name matches a
  common table expression in the same statement. This spec records that and does
  not fix it early, because one step carries one behaviour change.
- The referenced node keeps its two-part identity. Two Databases that hold one
  bare name still share one node. Step 2b separates them in the full keys of an
  Execution Path, which read the database from each relationship. The node
  itself never gains a database.
- No target produces one Execution Path per candidate schema. ADR-0035 records
  why.
- The `path_id` formula does not change. The ADR-0016 deduplication key and the
  merge key in `llamaindex-spec-rag` do not change.
- The `reads` and `writes` strings on an Execution Path keep their shape.
- The local wrapper functions inside the test files stay. A wrapper that names
  one file's intent, and holds no payload key, is that file's vocabulary rather
  than a copy of the payload shape.
- The second test fixture module keeps its own subject. It isolates the Derived
  Execution Evidence retention. It imports the one payload builder, and it does
  not join the check's allow list.

## Further Notes

### The Step 2a gate

Step 2a has a verification gate. An operator refreshes `EFNETDB` on a machine
that reaches the server, then copies the cache file here. The gate is met when
someone opens that copied file and finds an object whose schema is not `dbo`.

Step 2b does not start until that check passes. Every read-side test would
otherwise pass against a cache that never changed.

`EFNETDB` is the only evidence that can meet this gate. It holds objects in at
least three schemas: `COMMON`, `dbo`, and `HR`. It has never been refreshed, so
the size of the change to cache volume is unknown. Measure it after the first
refresh.

### The five existing caches

Five caches sit on disk today, and every one of them names `dbo` in its
filename: `PUR` at 118 MB, `ETON` at 833 KB, `STC` at 763 KB, `Response` at
676 KB, and `SysErrorRecord` at 39 KB.

Step 2a invalidates all five. Until replacements are copied here, a question
about any of those five Databases returns an empty answer. The read-side tests
stay green throughout, because Seam 1 builds its own payload.

Issue 7 therefore names this in its Blocked by line: the SQL data update runs
elsewhere and the files arrive here first. The issue's own check reads the files
on disk. It confirms that each filename has two parts and that each meta file
carries the new format version.

### No refresh between the listing commit and the identity commit

The listing commit of Issue 5 produces a payload that carries a schema on each
object, while the cache identity still names one schema. A refresh between that
commit and the identity commit writes a cache whose objects state `COMMON` and
whose identity states `dbo`. No issue asks an agent to run a refresh, and the
operator action under Preconditions runs after Step 2a is complete. That state
therefore never reaches a file. Deploy those two commits together.

The analyzer commit is different. Its shape does reach a file: an operator runs
the repair tool, and then reads the repaired graphs until Step 2b lands. That is
why the graph format version rises with it.

### Findings this spec has not yet decided

An architecture review of this spec produced the preparatory identity issue
above. It also produced findings this spec has not yet acted on. They are
recorded here because this spec returns to `ready-for-agent` only after they are
decided, and two of them lose an answer.

The index finding is decided and no longer listed. It is written into "The index
states its own format version", into Documents, into issue 2, and into issue 7.

The cache-directory finding is decided and no longer listed. It is written into
"The SQL Cache Identity module", into Cross-repository coordination, into issue
2, and into issue 4.

The contract version finding and the graph version finding are decided and no
longer listed. Both are written into "One test fixture module", into issue 1,
and into Seam 3. The census that produced the contract finding was wrong: the
eight literals sit in four test files, not six.

The Execution Path identity finding is decided and no longer listed. It is
written into story 7, into "The table match", into Documents, into issue 7, into
issue 8, into Seam 1, and into Out of Scope. The decision removes the one path
per candidate schema that produced the collision, so no `path_id` changes.

The cache-wide `schema` field finding is decided and no longer listed. It is
written into stories 63 and 76, into "One SQL cache holds one Database", into
"The schema field on the payload", into "The Execution Graph payload", into
"The SP Catalog", into issue 5, and into the testing decisions.

The hard-`dbo` comparison finding is decided and no longer listed. It is written
into "What each call site holds", into issue 5, into issue 7, and into Seam 1.

The excluded-schema finding is decided and no longer listed. It is written into
the Solution, into story 66, into "The refresh", into "The object listing", and
into Seam 2. The rule moves out of the query and into a filter over the returned
rows, so Seam 2 tests an outcome and not a string. The finding said three of
the four schemas cannot appear. That was wrong for `guest`: a user can create
objects in `guest`, and the catalog views list them. Two of the four cannot
appear. We verified this on SQL Server 2019 (15.0.4153.1). A user with ALTER
permission on the `guest` schema created a table in `guest`.
`INFORMATION_SCHEMA.TABLES` listed the table. A create in `sys` or in
`INFORMATION_SCHEMA` failed with error 2760.

The findings below still block this spec. One of them is new, and the review
that produced the others did not raise it.

- **The Database Invocation merge re-merges what Step 2b separates.** The
  analysis merge module's normalizer deliberately joins a qualified name to a
  bare one, and this spec keeps that merge on the ground that the C# side writes
  no schema. Story 12 contradicts that ground, and the merge's own fallback reads
  the first entry of the stored-procedure chain, which is always written as
  `schema.name`. After Step 2b, two procedures whose schemas differ merge into one identity. ADR-0035 does not change this finding: a procedure node comes from the listing and carries its own schema, so the merge collapses two proven schemas.
  The two-bucket rule this spec already writes for the two catalogs is the fix:
  merge a name that states no schema, and never merge two names that state
  different ones.
- **The host's common-table-expression exclusion compares both forms.** Out of
  Scope states it compares the bare name only. It compares the bare name and a
  composed `schema.name`. The behaviour holds, because T-SQL cannot qualify a
  common table expression, but the note is half true of the code.
- **Two more sites in `llamaindex-spec-rag` key on a stored-procedure chain.**
  The reverse-lookup dedup and the cross-system evidence identity lowercase each
  chain entry and keep the schema, so they treat a qualified name and a bare one
  as two identities while the merge treats them as one. They are the right
  behaviour and should stay; the census of four sites should say so, and should
  add the grounding module's normalizer as a fifth.
- **The Candidate Database Set intersects on a case-sensitive Database name.**
  Its key normalizes the server and only strips the Database name. Step 2b adds a
  field naming a Database that a full key states, and that name's case is
  whatever a T-SQL author typed. Decide whether that field feeds the
  intersection.
- **The evaluation repository builds a cache payload by hand in two test
  files.** Both write an Execution Graph payload with no graph format version at
  all, and the second cache-directory reader named under Cross-repository
  coordination consumes that shape. This is
  the same failure the twelve stale versions had in this repository, and issue 1
  cannot reach it: each issue changes one repository, and this spec has already
  rejected a shared package. Decide whether that repository gets its own fixture
  module, and in which issue.

### Other notes

The five currently cached Databases contain no non-`dbo` user schema. Their
two-part graph nodes named `WorkTable` and `Common` are cross-database
references whose database part was discarded by the analyzer; they are not
schemas. This is the defect the analyzer change fixes.

Step 2a crosses two repositories. Deploy issues 5 and 6 together.

This spec is `draft`. The architecture review that produced it settled the
preparatory identity issue, and left the findings under "Findings this spec has
not yet decided" open. A later interview settled the contract version finding
and the graph version finding, and it widened issue 1 to carry both. That
interview also raised one finding of its own, over the evaluation repository's
hand-built payloads. A third interview settled the cache-directory finding. It
gave the cache store one reader of that directory, moved the repair tool and the
server reverse-derivation onto it, split issue 2 into two commits, and gave the
evaluation repository's second reader to issue 4. A fourth interview closed the
index finding's loose ends. It named the index version constant and its payload
field, gave the backfill tool to issue 2's second commit, moved every sentence
that describes the index onto issue 7, and added one backfill test case. It also
ruled that a manual sentence belongs to the issue that changes the behaviour it
describes, which gave one advanced manual example to issue 5. That interview
decided none of the findings above. It returns to `ready-for-agent`
when the remaining findings are decided, and before any issue opens.

A fifth interview settled the Execution Path identity finding. It reversed story
7: an unproven schema now marks one Execution Path and does not multiply it. It
wrote the table match rule, gave an Execution Path two full-key fields, named
the cross-database field `stated_database`, and added ADR-0035 to the documents
issue. It decided none of the other findings. It only reworded the Database
Invocation merge finding, which the reversal does not change.

A sixth interview answered a review finding: the identity commit's site list
stopped at the cache reader. The review measured the missing sites against
today's code. The preparatory identity issue already absorbs most of them, so
the interview rewrote the list against the code that issue leaves behind. The
list now names each site that still reads a schema, and a grep check backs it.
The interview gave the server reverse-derivation a match on the identity's
Database field, and it made the reverse parse a method of the identity. It
added a test case for a Database name that holds `__`. It gave the data status
tool and the object location lookup to issue 2. It moved the meta file's and the
Object Location Index's `schema` fields into the identity commit, which
narrowed the cache-wide `schema` finding to two readers. It deleted three
object location tests at the identity commit, and it left the merge they cover
to issue 7.

A seventh interview settled the cache-wide `schema` finding. It gave the
payload field and the meta field to two different commits. The listing commit
deletes the payload field and its three readers, and the cache store no longer
writes that field for one commit. The identity commit deletes the meta field. The
interview replaced "the schema the cache states" with `dbo`, written directly by
the analyzer commit. It rewrote story 76 and story 63. It ruled that each of
issue 5's three commits leaves the suite green on its own, and it added one cache
store test case that guards against the field's return. It found that the test
fixture's meta write already follows the cache store, under issue 2.

An eighth interview settled the hard-`dbo` comparison finding. It found that the
cached object lookup is not a bare-name lookup: every node it receives comes
from the listing. The listing commit therefore removes its `dbo` fallbacks, not
Step 2b. It found that the graph object lookup breaks at the analyzer commit,
because each function reference becomes an object there. It gave that lookup the
two-bucket rule at Step 2b, and it ruled that a function reference that states
another Database matches no local node. It added three path evidence cases to
Seam 1. It decided none of the other findings.
