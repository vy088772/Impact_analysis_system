# 02 — A reverse lookup keeps every fact it has

**What to build:** A reverse lookup response states everything the service
learned about one table, and it never deletes a fact to make the answer shorter.

An analyst asking which programs write a table still receives proven writes
only, and now also learns how many paths were excluded because the service could
not prove them. An analyst asking which programs touch a table receives those
paths too, each carrying its Evidence Status and the reason it stayed
unresolved. Unresolved Dynamic SQL becomes visible instead of absent — nine such
operations exist in the PUR graph and no repair will ever prove them.

One program that reaches one table through two stored procedures now appears
twice, once per Execution Path. One program that reads a table through one
stored procedure and writes it through another reports both facts.

This ticket carries two decisions on purpose. Landing the first alone would
regress: an unproven write would take the file's single seat, a caller filtering
for proven writes would then discard it, and the proven read it displaced would
already be gone.

Read [ADR-0015](../../../docs/adr/0015-an-unproven-execution-path-is-reported-not-dropped.md)
and [ADR-0016](../../../docs/adr/0016-a-table-match-is-deduplicated-by-execution-path-not-by-file.md)
first. Each records the alternative it rejected.

**Blocked by:** None — can start immediately. Note that another effort,
`.scratch/table-reverse-lookup-cost/`, holds uncommitted work in the same query
module. Read the working tree before you start, and land after it or coordinate.

**Status:** ready-for-agent

- [ ] A path the service cannot prove appears in the response, with its Evidence
      Status and the reason it is unresolved.
- [ ] That path claims no mutation.
- [ ] A proven-writes request returns exactly what it returns today, plus a
      count of the records it excluded.
- [ ] One program reached through two stored procedures produces two records.
- [ ] One program with a proven read and an unproven write on one table produces
      both records.
- [ ] Two identical Execution Paths produce one record.
- [ ] The record count for one busy table is measured before and after this
      change, and both numbers are recorded on this ticket before it closes.
- [ ] The existing query-module tests are updated where they assert the present
      delete behaviour, and every other test in the suite still passes.
