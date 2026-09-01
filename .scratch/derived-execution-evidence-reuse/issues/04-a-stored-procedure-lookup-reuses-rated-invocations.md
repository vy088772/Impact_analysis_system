# 04 — A stored-procedure reverse lookup reuses rated Database Invocations

**What to build:** Asking twice which programs call a stored procedure rates the
repository's C# facts once, not twice. The second question is answered from the
evidence the first one derived, and the answer is identical either way.

This is the smaller half of the reuse, taken first on purpose. The stored-
procedure lookup needs only the rating step, so it exercises the retention and
the freshness rules without the path-building step on top. If the freshness
design is wrong, it is found here, on the lookup that is not carrying the bulk of
the measured wait.

Reuse arrives guarded, never on its own. Serving retained evidence after one of
its inputs has moved does not produce a slow answer, it produces a confidently
wrong one, and nothing in the response would reveal it. That is why the validity
stamp is part of this ticket rather than a follow-up, and why each invalidation
trigger is proven separately instead of collectively.

**Blocked by:** 02 (the baseline can never be taken once behaviour changes),
03 (there is no key without an explicit scope).

**Status:** ready-for-agent

- [ ] Two consecutive stored-procedure lookups in one scope rate the repository's
      C# facts once
- [ ] The answer is identical with reuse active and with reuse defeated — for a
      stored procedure with matches and for one with none
- [ ] Each retained derivation carries a validity stamp covering the repository
      scan, the SQL cache it was joined against, the external wrapper contract,
      the contract registry, and the wrapper review exclusions
- [ ] A mismatch on any single stamped input causes a fresh derivation, proven by
      one test per input, each also asserting the answer reflects the new input
- [ ] An explicit refresh always derives again and replaces the retained entry,
      and is never served from retention
- [ ] The lookup's response is unchanged in shape and content
- [ ] Tests are driven through the lookup itself, the seam this area is already
      tested at, and assert derivation counts rather than elapsed time
- [ ] Retained state is snapshotted and restored around tests, following the
      existing fixture that does this for the SQL cache's in-memory retention, so
      no test passes because of another test's leftovers
