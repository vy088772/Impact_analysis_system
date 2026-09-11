# 16 — Coverage report: two ratios per system, with named reasons

**What to build:** A maintainer can re-run the acceptance measurement at any time and see, per
System, how far the analysis actually got.

Two ratios are reported: Database Invocations that resolve an Executed Procedure
Name, and Database Invocations that resolve a Resolved Connection Source. They
are reported separately, because the measured repositories have opposite
bottlenecks and a combined number would hide which one is stuck.

Every invocation below the line names its reason. A ratio alone cannot tell a
resolution that improved from one that merely became confident, so the reason
codes are what make the number actionable.

**Blocked by:** 07, 09, 13.

**Status:** done

- [x] The report states, per System, the share of Database Invocations that resolve an Executed Procedure Name.
- [x] The report states, per System, the share of Database Invocations that resolve a Resolved Connection Source.
- [x] The two ratios are reported separately and are never combined into one number.
- [x] Every unresolved invocation is counted under a named reason code.
- [x] The reason codes distinguish at least: command text arriving across a method boundary, a lookup key outside the connection strings namespace, no project file above the source, and no semantic model for the project.
- [x] The report runs against a named System and is repeatable without a full re-scan where a current cache exists.
- [x] The WebForms System is reported by the same command, so its numbers can be compared against the captured baseline.

## Note

### Where the code is

`service/coverage_report.py` builds and renders the measurement; `tools/coverage_report.py`
is the command. The module never scans and never reads configuration — the caller hands it a
scan result and the SP Catalog — so the same measurement runs against a cached scan and a fresh
one without knowing which it was given.

`service/system_targets.py` is new: resolving a named System to the local scan roots that hold
its source. `discover_external_wrappers` had that rule and the scan-cache readiness mapping
inline; two commands now need them, so they moved to one place and that tool imports them.
Nothing about its behaviour changed.

### The reason a report reads, and the one it names itself

Almost every reason code already existed. `command_text_method_parameter` (ticket 07),
`no_project_connection_scope` / `root_configuration_namespace_not_connection_strings` /
`context_type_not_registered` / `field_held_connection_not_traced` (tickets 08 and 09),
`wrapper_source_unavailable`, `inline_sql`, `terminal_sink_unresolved` and the rest come from
the rule that produced them, so a number here and a log line there read as the same fact. The
report contributes two names of its own:

- `no_semantic_model` — the project reports Semantic Binding Availability other than
  `available`, and the invocation's own reason is one of the three absences a missing model
  actually produces (`dynamic_command_text`, `receiver_type_missing`,
  `declaring_type_unresolved`). A named reason always wins over it: a command text that
  arrives as a method parameter is a fact about the call, not about the model.
- `no_connection_expression` — the call site names no connection at all, because an external
  wrapper opens its own inside an assembly this analysis cannot see. That is a different
  absence from a lookup key that resolved to nothing.

**`no_semantic_model` is deliberately never reported on the connection ratio.** The first real
run exposed why: ATV filed 176 of its 190 connections under it, and every one of those is a
`Web.config` lookup that never needed a semantic model in the first place. Connection
resolution is a lookup-table rule; the one shape that does need the model — a receiver's
declared context type — already reports `context_type_not_registered` through the tracker. The
ticket's four reason codes stay four distinct, reachable codes; they simply live on the ratio
whose absence they actually explain.

### Two ratios, one denominator

Both shares are taken over the same denominator: every Database Invocation the scan holds. An
invocation the analysis proved runs inline SQL is therefore below the procedure-name line — but
under `inline_sql`, which names it honestly, so the number stays comparable with the captured
baseline instead of being quietly excluded from it.

A System with no invocations reports `ratio: null`, never `0.0`. Nothing measured is not the
same as nothing resolved. The same rule covers a scan root that was skipped: it still occupies
a row, carrying `scan_cache_missing` / `scan_cache_stale` / `scan_cache_invalid`, so a System's
shares never read as if they covered a root the command never opened.

### Measured

`python -m tools.coverage_report --system Y-DOCs_TTRDQ` (the WebForms baseline System):

```
Y-DOCs_TTRDQ  database_invocations=6375
  executed_procedure_name: 8.5% (543/6375)
    wrapper_source_unavailable: 5582, inline_sql: 139, multiple_sql_commands: 61,
    no_semantic_model: 32, terminal_sink_unresolved: 14, wrapper_sink_unresolved: 2,
    overload_not_found: 1, wrapper_mode_unresolved: 1
  resolved_connection_source: 1.4% (90/6375)
    connection_source_unresolved: 6195, no_connection_expression: 90
```

First run 66s (no current cache, so it scanned once); second run 0.36s with identical numbers.
Repeatable without a re-scan, as the checklist asks.

`connection_source_unresolved` at 6195 is the generic fallback, and it is the largest single
bucket in the report — which is exactly what ticket 17 exists to sharpen.

### Verification

`tests/test_coverage_report.py`, 19 tests: 13 on the measurement, 6 on the command. Full suite
after: 853 passed / 11 failed / 5 skipped — the same eleven pre-existing failures as ticket 15,
up from 834 passed.

Code review (Standards + Spec sub-agents): no hard violations. One Standards finding fixed —
the two-ratios test asserted an absence without asserting its reason, which the spec's Testing
Decisions forbid.
