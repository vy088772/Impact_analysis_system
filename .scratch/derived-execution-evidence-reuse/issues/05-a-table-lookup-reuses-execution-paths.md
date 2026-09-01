# 05 — A table reverse lookup reuses Execution Paths as well

**What to build:** Asking which programs touch a table stops rebuilding every
Execution Path in the SQL Execution Graph on every request. This is where the
measured eighty-eight to ninety-seven seconds goes away.

The decisive test is two questions naming two different tables in one scope. If
they derive once between them, the claim that the derivation is independent of
the question is no longer an argument — it is enforced. That is the property the
whole effort rests on, and it cannot be demonstrated by repeating one question.

The table lookup blends two sources of matches: those found by comparing table
names embedded directly in C# source, and those found by following the SQL
Execution Graph. Only the second is affected here. The blending and its
preference rule stay exactly as they are, because a faster lookup that quietly
changed which of two overlapping matches wins would be a changed answer.

**Blocked by:** 04 (extends the same retention and the same freshness rules).

**Status:** ready-for-agent

- [ ] Two consecutive table lookups in one scope build Execution Paths once
- [ ] Two lookups naming different tables in one scope derive once between them
- [ ] The answer is identical with reuse active and with reuse defeated — for a
      table with matches, a table with none, and a `write_only` query
- [ ] `write_only` filtering behaves exactly as it does today
- [ ] The preference rule that blends embedded-SQL matches with graph-derived
      matches is unchanged
- [ ] Path building is covered by the same validity stamp and the same explicit-
      refresh rule as the rating step, with no second, weaker set of rules
- [ ] The lookup's response is unchanged in shape and content
- [ ] Tests assert derivation counts rather than elapsed time, at the same seam
      as the previous ticket
