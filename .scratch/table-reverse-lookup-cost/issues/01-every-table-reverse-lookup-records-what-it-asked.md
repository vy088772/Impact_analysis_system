# 01 — Every table reverse lookup records the table and the scope it asked about

**What to build:** After this ticket, every table reverse lookup the service
performs leaves a record naming the table it was asked about and the Derived
Execution Evidence Scope it ran in. An engineer can then read recorded traffic
and answer how many distinct tables one scope is asked about before its inputs
change.

That question is unanswered today, and it decides the shape of the stored
evidence in a later ticket. The recorded evaluation set cannot answer it: its
six table questions all name one table, so it can never show a scope being
asked about a second one.

The record is written where the lookup enters the service, not where the Agent
calls a tool. A lookup that runs before an Agent exists must be recorded too,
because that path is the one that raises Object Kind Ambiguity and it is the
slowest recorded group.

This ticket changes no behaviour and no timing. It is observability only, and
it lands before the baseline run so that the baseline itself contributes
traffic.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A table reverse lookup writes one record naming the requested table name.
- [x] The same record names the Derived Execution Evidence Scope the lookup ran
      in, so two systems asking about one table stay distinguishable.
- [x] A lookup performed before an Agent is constructed is recorded the same
      way as one an Agent requested.
- [x] The records a lookup returns are unchanged, field for field.
- [x] No existing timing figure changes meaning.

## Notes

Seam: drive `find_by_table()` and assert on the emitted record. This is the
same seam `tests/test_derived_execution_evidence_retention_bound.py` already
drives for retention behaviour.

Do not add a second recording point for the Agent's own tool calls. The Agent
already records its decisions, and this record answers a different question.

The scope identity is already assembled in one place for every request. Reuse
that value rather than rebuilding the identity for the record.

## Implementation note

Landed in `service/analyze_service.py`: `find_by_table()` now builds the
`DerivedExecutionEvidenceScope` once, right after `roots` is resolved, and
calls a new `_record_table_reverse_lookup(table_name, scope)` helper (one
`print()` line) before doing any matching. The existing `if req.database:`
branch was changed to reuse that same `scope` object instead of building a
second one.

The record is emitted only past the two early-return guards (empty
`table_name`, and a `cache_only` miss that has not resolved real scan roots
yet) — a `cache_only` skip stays unrecorded on purpose, since recording it
would require doing exactly the scan work `cache_only` exists to avoid. Every
lookup that actually runs — with or without `database` set, i.e. including the
pre-Agent, Object Kind Ambiguity shape — passes through this one point.

Tests added in `tests/test_table_reverse_lookup_traffic_record.py`, driving
`find_by_table()` directly and asserting on the printed record via `capsys`
(same style as `tests/test_derived_execution_evidence_retention_bound.py`).
Confirmed red on the pre-change code, green after. Full suite run alongside:
12 pre-existing failures, unrelated to this change and present on both sides
of the diff (stale fixtures / missing ODBC driver in this environment).

Ran `/code-review` (Standards + Spec axes) before committing and fixed both
findings it raised: the printed line now names all five
`DerivedExecutionEvidenceScope` fields, including `db_name` (previously
omitted, though always empty today since `FindByTableRequest` has no
`db_name` field), and the message text was changed from a half-English/
half-Chinese hybrid to plain Chinese using this file's own 反查 vocabulary,
matching `_evict_for_new_scope`'s existing print style. One review note with
no code change: "a lookup before an Agent exists is recorded the same way as
one an Agent requested" holds trivially, since `find_by_table()` has exactly
one production call site (`service/api.py`'s `/find_by_table` route) and no
Agent-vs-pre-Agent branching inside it -- there was nothing to route
differently to record differently.
