# 05 — Add a regression test guarding the dual-fact identity/receiver pairs

**What to build:** A test proving that `DbInvocation`'s ten dual-fact field pairs (the invocation's own identity vs. the external wrapper's identity, e.g. `implementation_identity`/`wrapper_implementation_identity`, `receiver_type`/`wrapper_receiver_type`, `external_wrapper_method`/`wrapper_method`) can hold different values on the same invocation and both survive independently through serialization — the safety net against a future contributor "cleaning up" this pattern into a single collapsed field the way ticket 02 and 03 correctly collapse the true duplicates.

**Blocked by:** None — this guards existing, unchanged behavior and can land at any point, independently of the other tickets.

**Status:** ready-for-agent

- [ ] A new test constructs a `DbInvocation` (or uses the existing fixture-construction pattern already used in `tests/test_csharp_analysis_gateway.py`) where at least `implementation_identity` differs from `wrapper_implementation_identity`, and `receiver_type` differs from `wrapper_receiver_type`.
- [ ] The test asserts both values in each pair survive independently in the invocation's serialized output (via `invocation_wrapper_evidence_fields`/`_serialize_db_invocation`), i.e. neither value silently overwrites or falls back to the other except where the existing, intentional `receiver_type = invocation.receiver_type or wrapper's` fallback already applies (assert that fallback behavior explicitly too: when `receiver_type` is empty, the wrapper's value is used; when both are set, the invocation's own value wins).
- [ ] The test's docstring or a comment states plainly that this pair is two independent facts, not an alias, so a future reader doesn't mistake it for a leftover of the alias-collapse work in tickets 02–04.
- [ ] Full existing test suite passes.
