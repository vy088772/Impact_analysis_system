# 12 — The documents record the decisions

**Spec issue:** 8

**What to build:** A future reader finds why one cache holds one Database, why
the index states its own version, and why an unproven schema marks one
Execution Path. The glossary defines each new term once.

See "Documents" in the spec.

**Blocked by:** 11

**Status:** done

- [x] ADR-0033 records that one SQL cache holds one Database, and why one cache per schema was rejected.
- [x] ADR-0034, "The Object Location Index States Its Own Format Version; an Incomplete One Is Absent", exists.
- [x] ADR-0012 gains an `Amended by ADR 0034` note in the form ADR-0004 uses.
- [x] ADR-0035, "An Unproven Schema Marks One Execution Path; It Does Not Multiply It", states its reasons and its two rejected alternatives. ADR-0015 and ADR-0016 gain no note.
- [x] `CONTEXT.md` gains a Canonical Object Identity entry that carries the two-bucket lookup rule.
- [x] `CONTEXT.md` gains an Unproven Schema entry that names `unproven_schema`.
- [x] `CONTEXT.md` gains a test fixture entry that names the check.
- [x] `CONTEXT.md` gains a C# Scan Result entry that states it is not a Scan Record.
- [x] The Database Invocation entry gains the sentence that one entry method through one call site is one Database Invocation, whichever SQL cache reports it.
- [x] The cache store docstring that states schemas collapse to one key is corrected.

## Notes

**2026-09-29 (done):**

- **Precondition checked.** The `database-invocation-identity-is-the-call-site` issue in `llamaindex-spec-rag` is done, so the Database Invocation sentence states a rule that exists.
- **Cache store docstring.** Commit `39b30e3` (ticket 11) already removed the sentence "dbo.Orders 與 sales.Orders 收斂成同一個 key". The docstrings at `service/sql_cache_store.py` lines 6, 18, and 161 now say that one cache covers every schema. This ticket changed no code.
- **Not in the checklist: ADR-0009 gains an `Amended by ADR 0033` note.** ADR-0009 named the identity `(server, database, schema)`, and ADR-0033 changes that part. The spec rule "an `Amended by` note states that a decision changed" covers this case.
- **Not in the checklist: the Object Location Index entry refers to the two-bucket rule.** The rule now sits once, in the Canonical Object Identity entry. The Object Location Index entry also links ADR-0012 and ADR-0034, and the SQL Cache Identity entry links ADR-0033.
- **The rule differs at each site.** The spec bullet "falls back to the bare bucket … carries an Unproven Schema mark" is true of the index alone. The SP Catalog and the table match fall back only to an entry that states no schema. The index gives no mark. The glossary states each difference.
- **New section.** The Test Fixture Module entry sits under a new `## Testing` section.
- **ADR-0035 title.** The title comes from the spec word for word. The Decision states that the mark sits on the match record of the one path.
- **Review.** Standards: the review found three false or broad claims in the first glossary draft and sentences longer than 25 words. All are fixed. Spec: no missing item. The three choices above are judged acceptable.
- **Tests.** The change touches documents only, so no suite ran.
