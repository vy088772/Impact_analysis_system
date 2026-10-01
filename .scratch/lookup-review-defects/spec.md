# A Reverse Lookup Honors Its Limits And Names Its Gaps

Status: ready-for-agent

Seven defects came out of a review of the cross-system reverse lookup and its
neighbours. Five of them live in the companion repository `llamaindex-spec-rag`
(the client). One of them (the Database identity) also needs a change in this
repository (the Impact server). Two of the seven are not yet proven: the work
for them starts with a test that may turn out green. This spec records the
decisions from the grilling session. It writes no tickets: `to-tickets` slices
the work.

## Problem Statement

A person who asks a question across many Systems gets answers that hide their
own gaps.

- A reverse lookup by stored procedure or by table does not count against the
  request ceiling of the run. A run can send more Evidence requests than its
  ceiling allows.
- When the agent stops with no analyzed code but with a finalized answer, the
  command line labels the answer "not analyzed" and hides the report path. The
  person cannot find the report.
- In mode 4, a wrong finalization setting fails only after the whole agent run.
  The person waits for a full analysis and then sees an error.
- A Database name that exists on two hosts makes `/find_by_sp` and
  `/find_by_table` answer 409. The client reads that 409 as "this Database is
  not scanned". The person is told to scan a Database that is already scanned.
- Several copies of the program-name suffix rule exist. The review says two of
  them do not strip `.cshtml` and `.vue`. This is not proven: a first reading
  finds both suffixes in every copy.
- One test that guards the write-access type list fails with a bare
  `StopIteration`, and the message does not name its cause.
- `/path_evidence` may find program files by substring while `/analyze` finds
  them by Program Screen. For the program name "Order" the two may disagree.
  This was found by reading and was never run.

## Solution

Every reverse lookup spends from the one request budget of the run. When the
budget is spent, the lookup lists each System it did not read, with the reason
"request ceiling reached". It does not stop silently and does not abort the run.

The command line shows the report path whenever an answer exists. Its heading
tells a finalized answer from a run that analyzed no code. Mode 4 builds its
finalization options before the agent starts, so a wrong setting fails at once.

The lookup endpoints accept an optional `db_server`. The client sends it. A
Database name that lives on more than one host gets its own error code, and the
client reports it as its own reason: "the Database exists on several hosts, name
the host". It no longer reads as "not scanned".

For the two unproven defects, a test comes first. The suffix test feeds every
suffix to every copy. The program-file test runs the "Order" case against both
endpoints. A green test closes the defect with a written finding. A red test
gets the fix below.

## User Stories

1. As an analyst, I want every reverse lookup to count against the request
   ceiling of the run, so that one run never sends more requests than I set.
2. As an analyst, I want a lookup that hits the ceiling to list the Systems it
   did not read, so that I know which answers are missing.
3. As an analyst, I want each unread System to carry the reason "request ceiling
   reached", so that I tell a ceiling stop from a failed request.
4. As an analyst, I want the run to continue after the ceiling is reached, so
   that I still receive the answers that were read.
5. As an analyst, I want a stored-procedure lookup and a table lookup to share
   one budget, so that the total request count stays predictable.
6. As an analyst, I want the command line to show the report path whenever an
   answer exists, so that I always find my report.
7. As an analyst, I want a finalized answer with no analyzed code to carry its
   own heading, so that I do not read it as "nothing was analyzed".
8. As an analyst, I want the heading "analyzed no code" to appear only when no
   answer exists, so that the heading matches the real state.
9. As an analyst, I want a wrong finalization setting in mode 4 to fail before
   the agent starts, so that I do not wait for a full run.
10. As an analyst, I want the failure message to name the wrong setting, so that
    I fix it in one step.
11. As an analyst, I want mode 4 and the other modes to validate settings at the
    same point, so that the failure time does not depend on the mode.
12. As an analyst, I want a lookup by stored procedure to name the host when a
    Database exists on two hosts, so that the lookup reads the right cache.
13. As an analyst, I want a lookup by table to name the host the same way, so
    that both lookups behave alike.
14. As an analyst, I want `/find_by_sp` and `/find_by_table` to accept the same
    `db_server` that `/path_evidence` and `/flow_chain` accept, so that the four
    endpoints agree.
15. As an analyst, I want a Database that exists on two hosts to be reported as
    "several hosts, name the host", so that I do not scan a Database that is
    already scanned.
16. As an analyst, I want a Database that is truly not scanned to still read as
    "not scanned", so that the two reasons stay apart.
17. As an analyst, I want a lookup without `db_server` to keep working for a
    Database on one host, so that old calls do not break.
18. As an operator, I want the client to ship before the server, so that an old
    client never meets the new error code.
19. As an operator, I want an unknown 409 code to stay an error, so that a new
    server problem never hides as a skip.
20. As a developer, I want one program-name suffix rule per repository, so that
    two copies never drift apart.
21. As a developer, I want a test that feeds all seven suffixes to every copy,
    so that a missing suffix shows at once.
22. As a developer, I want a green suffix test to close the defect with a
    written finding, so that nobody re-opens a false report.
23. As a developer, I want the write-access type test to say why it fails, so
    that I know the sibling checkout is on the wrong branch.
24. As a developer, I want that message to name the commit that holds the list,
    so that I switch to the right branch.
25. As an analyst, I want `/path_evidence` and `/analyze` to agree on which
    program files a name matches, so that the two answers never contradict.
26. As an analyst, I want a program name such as "Order" not to match
    `OrdersController.cs`, so that I do not receive unrelated files.
27. As a developer, I want a test that runs the "Order" case against both
    endpoints before any fix, so that the fix answers a proven defect.
28. As a developer, I want a green "Order" test to close the defect with a
    written finding, so that I do not change two endpoints for no reason.

## Implementation Decisions

- **Request budget.** The stored-procedure lookup and the table lookup receive
  the request budget of the agent run and pass it to the shared cross-system
  lookup, which already accepts it. The agent run state is the one owner of the
  budget. A lookup never creates its own budget.
- **Ceiling reached.** The shared lookup adds each unread System to
  `unread_systems` with a new reason, "request ceiling reached". It does not
  raise. It adds no new failure channel. The report and the agent answer name
  the reason in plain words.
- **Run finish display.** When an answer exists, the command line prints the
  report path. The heading has two forms: finalized answer, and no code
  analyzed. The empty-scope branch picks the heading from the real state of the
  result.
- **Mode 4 settings.** Mode 4 builds its finalization options before the agent
  runs, as the other modes already do. A wrong setting raises before any request
  leaves the process.
- **Database host on the lookup endpoints.** The request schemas of
  `/find_by_sp` and `/find_by_table` gain an optional `db_server`. The server
  passes it to the same cache-identity resolution that `/path_evidence` and
  `/flow_chain` use. See the SQL Cache Identity entry in `CONTEXT.md` and
  ADR-0033: one cache holds one Database, and the identity is the normalized
  `(server, database)` pair. A lookup that names no host keeps today's
  behaviour for a Database on one host.
- **Several hosts.** When a Database name resolves to more than one cache and no
  host is named, the server answers with a new, distinct error code. The code
  `sql_execution_graph_required` stays for "not scanned". The client maps the new
  code to a new unread reason that tells the person to name the host. The client
  keeps raising on any 409 code it does not know.
- **Rollout order.** The client ships first. It understands the new code and
  sends `db_server`. The server ships second. An old server ignores the optional
  field, so the client is safe alone. An old client would raise on the new code,
  so the server must not ship first.
- **Suffix copies.** Each repository keeps one definition of the program-name
  suffix rule. The client has copies in the grounding module and in the revision
  query module. The server has copies in the analyze service. Other copies,
  such as the one in the evaluation tree, join the same cleanup. The two
  repositories cannot share code, so each keeps its own single definition. The
  work starts with the all-suffix test. A copy that differs in logic, such as
  path handling, keeps its logic and calls the one suffix list.
- **Write-access type test.** The code stays as it is. The test replaces its
  bare `next(...)` with an assertion that states the cause: the sibling
  checkout lacks the list, and the person must switch to a branch that holds
  commit 5a9aec0.
- **Program-file matching.** The "Order" test runs first. If it is red,
  `/path_evidence` resolves program files through the same program resolution
  that `/analyze` uses, so the two endpoints give one answer. `/analyze` does not
  relax to substring matching. If the test is green, no code changes.

## Testing Decisions

- A good test checks external behavior: what the lookup returns, what the
  command line prints, what the endpoint answers. It does not check which
  function calls which.
- **Cross-system lookup entry** (client): tests for the ceiling case and for the
  several-hosts case. Check `matches` and `unread_systems`, including the
  reason string. Prior art: the cross-system lookup locate-cost test and the
  scoped-lookup recording test.
- **Command line output** (client): the empty-scope case with an answer prints
  the report path and the finalized heading. The case with no answer keeps the
  old heading. Prior art: the run CLI input test.
- **Mode 4 entry** (client, new seam): a wrong setting raises and the fake agent
  runner records zero calls. This is the only new seam.
- **HTTP API** (server): `/find_by_sp` and `/find_by_table` with `db_server`,
  with a Database on two hosts and no host, and with an unscanned Database.
  Also the "Order" case against `/path_evidence` and `/analyze`. Prior art: the
  path evidence API test and the exact path evidence test.
- **Suffix copies:** one shared case list of the seven suffixes, run against every
  copy in its repository. Prior art: the mirror module of the canonical object
  identity, which passes the same shared cases in both repositories.
- **Write-access type test:** a check that, with the list absent, the failure
  message names the cause. No production behavior changes.
- The two unproven defects need a red test before any fix. A green test closes
  the defect and records the finding in the ticket.

## Out of Scope

- A shared package between the two repositories.
- A new budget kind, or a change to the size of the existing ceiling.
- A redesign of the Program Screen rule itself.
- A change to the schema of the SQL cache or to its identity rule.
- A change to the lookup endpoints other than the optional `db_server` and the
  new error code.
- Fixing the sibling checkout branch of the person who saw the test fail.

## Further Notes

- Facts in this spec come from a read-only investigation. Two of them were not
  re-run: the six passing tests of the write-access type file, and the claim that
  every suffix copy lists `.cshtml` and `.vue`. The first test of each of those
  defects checks the fact.
- The defect "Failing parity test" showed 2 failed and 3 passed in the review.
  The investigation found 6 passed. The cause is the sibling checkout branch,
  not the code.
- The work spans two repositories. The client changes go to
  `llamaindex-spec-rag`. The server changes go here. Rollout order: client first.
- Suggested slices for `to-tickets`, by root cause: (1) limits and settings,
  (2) identity and host, (3) test message, (4) the unproven program-file match.
