# The FK Cascade Table Feature Is Removed

Status: ready-for-agent

This spec covers two repositories. This repository holds the analysis service.
The companion repository, `llamaindex-spec-rag`, holds the orchestrator that
calls the service. Both repositories change together.

The measurements in this spec come from the live SQL caches in
`data/sql_cache/`. A probe called the real adjacency builder and the real
breadth first search from the resolver module before the removal.


## Problem Statement

The system has a feature that reports "FK cascade tables" for each program. A FK
cascade table is a table that the feature thinks is related to a table that the
program reads or writes. The feature gives no value to the user, and it damages
the quality of the answer.

The user wants three outputs from this tool. The user wants the outline of a
program. The user wants the related source code. The user wants the SQL Server
stored procedures that the program calls. The FK cascade table is not one of
these three outputs.

The feature has three defects.

The feature does not change which programs the tool finds. The feature adds one
line of text to the prompt for the AI. The feature also adds table names to the
grounding allowlist. The grounding allowlist is the set of names that the
hallucination check accepts as real. The main entry point is the reverse lookup
by table name. The reverse lookup does not use this feature at all.

The feature damages the grounding allowlist. For a master table, the feature
returns up to 50 unrelated table names. The hallucination check then accepts all
50 names as real. The AI can name these tables in an answer, and the check does
not stop it.

The feature gives the worst result where the user needs it most. The feature
infers a relation from the name of a primary key. This inference is a text
match, not a structural fact. For a detail table, the result is correct but
obvious. For a master table, the result is either noise or nothing.

The deployed configuration sets the tracking depth to 0, which turns the feature
off. The request schema still sets the default depth to 1. Any caller that does
not send the depth still gets the feature.

## Solution

Remove the FK cascade table feature completely from both repositories.

Remove the resolver module. Remove the depth field from the two request
schemas. Remove the cascade table field from the response schema. Remove the
configuration setting. Remove the seven places that consume the field. Remove
the feature from the documents. Regenerate the OpenAPI export.

Write a new Architecture Decision Record (ADR). An ADR is a document that
records one design decision and its reasons. The new ADR records this decision
and its measurements. The new ADR supersedes design decision 9 in the
integration design document.

Keep the historical records unchanged. ADR-0011 keeps its original text. The S3
milestone table keeps its original text. The new ADR explains what changed.

## User Stories

1. As an analyst, I want the answer to name only the tables that a program
   really reads or writes, so that I can trust the list of affected tables.
2. As an analyst, I want the hallucination check to reject a table name that the
   program does not touch, so that I can find an invented answer.
3. As an analyst, I want the command line output to show the outline, the source
   code, and the stored procedures only, so that I read less noise.
4. As an analyst, I want the prompt for the AI to hold only proven facts, so
   that the AI does not build an answer on a text match.
5. As an analyst, I want the answer to stay silent about a table relation that
   the database does not declare, so that I do not trust a guess.
6. As a developer, I want the request schema and the deployed behaviour to
   agree, so that I do not get a surprise from a default value.
7. As a developer, I want a direct call to the analyze endpoint to behave like a
   call from the orchestrator, so that I can test the endpoint alone.
8. As a developer, I want the response to hold no empty field that nobody
   reads, so that I understand the contract.
9. As a developer, I want the OpenAPI export to show the real contract, so that
   I can generate a client from it.
10. As a developer, I want the code to hold no module that the product does not
    use, so that I read less code.
11. As a developer, I want the union list in the merge step to name only the
    fields that the merge step really needs, so that the merge logic stays
    clear.
12. As a developer, I want the test suite to hold no test for a removed
    feature, so that the suite runs faster.
13. As a developer, I want the tests that use the cascade field as a marker to
    use a different marker, so that the tests keep their coverage.
14. As a maintainer, I want an ADR that records why the primary key inference is
    not sufficient, so that a later developer does not build the same feature
    again.
15. As a maintainer, I want the ADR to hold the measurements, so that a later
    developer can judge the decision without a new measurement.
16. As a maintainer, I want ADR-0011 to keep its original text, so that the
    record of the earlier decision stays honest.
17. As a maintainer, I want the S3 milestone table to keep its original text, so
    that the history of the build stays correct.
18. As a maintainer, I want the new ADR to name the design decision that it
    supersedes, so that a reader finds the current position.
19. As a reader of the manual, I want the manual to say nothing about a FK
    cascade table, so that I do not look for a feature that is not there.
20. As a reader of the integration design document, I want the document to
    describe the real response fields, so that I can build against it.
21. As a reader of the advanced handbook, I want the module list to name only
    the modules that exist, so that I can find each file.
22. As a reader of the readme, I want the feature list to name only the real
    features, so that I get a correct first impression.
23. As an operator, I want the environment file to hold no setting for a removed
    feature, so that I do not turn on something that is gone.
24. As an operator, I want the environment file comments to describe the real
    behaviour, so that I do not act on a wrong comment.
25. As an operator, I want the troubleshooting table to hold no row about an
    empty cascade table list, so that I do not chase a removed feature.

## Implementation Decisions

### Scope of the removal

The removal covers both repositories. The first repository holds the analysis
service. The second repository holds the orchestrator that calls the service.

### The resolver module

Remove the FK resolver module from the analysis service. Remove its dedicated
test file.

### The request schemas

Remove the tracking depth field from the analyze request schema. Remove the
tracking depth field from the flow chain request schema. Both fields currently
default to 1, which contradicts the deployed behaviour. The removal ends this
contradiction.

### The response schemas

Remove the cascade table field from the program result schema. Remove the
cascade table field from the forward chain result.

This is a breaking change to the API contract. The user confirmed that no
caller outside these two repositories reads this field. The removal is direct.
The response does not keep an empty field.

### The configuration setting

Remove the tracking depth setting from the orchestrator configuration. Remove
the matching entry and comments from the environment file. The current comment
says that the resolver queries the database when the cache is absent. This
statement is wrong. ADR-0011 removed that query.

### The consumers

Remove the seven places that read the cascade table field.

The analysis service builds the field in two places. One place is the analyze
path. The other place is the flow chain path.

The orchestrator reads the field in five places. The merge step unions the
field across caches. The forward chain merge unions the field across caches.
The command line prints one line. The context builder adds one line to the
prompt. The agent tool renderer adds one line to the prompt. The grounding step
adds the names to the allowlist.

The union list in the merge step drops to one field. The union of stored
procedure names stays.

### The OpenAPI export

Regenerate the committed OpenAPI export after the schema change.

### The new ADR

Add ADR-0031. Write it in English, to match the other ADRs in the directory.

The ADR states the decision. The primary key naming inference is not sufficient
for a cascade table report. The feature is removed.

The ADR states the reasons and the measurements.

The SQL cache holds no foreign key data. A cached table object holds three
fields only: the name, the columns, and the primary keys.

A primary key does not describe a relation. A primary key states that a column
identifies a row in its own table. It names no other table. A foreign key names
the other table. The databases declare primary keys only.

The primary key coverage is partial. The PUR database holds 401 tables. 216
tables have a primary key. 128 tables have a single primary key. The resolver
skips a compound primary key, so 32 percent of the tables can start an
inference. The other databases measure 72 percent, 32 percent, 100 percent and
0 percent for primary key coverage.

The inference fails on a master table. The PUR adjacency has 247 nodes and 346
edges. The largest fan-out is 65 for the Customers table. A depth of 1 from
Customers returns 50 tables, which is the cap. A depth of 2 returns the same 50
tables. The Quotation table returns 33 tables at depth 1 and hits the cap at
depth 2.

A filter does not rescue the inference. A filter that removes the temporary
tables, the work tables, the backup tables, the log tables and the system
tables gives this result. Customers returns 0 tables. Vendors returns 0 tables.
Quotation returns 0 tables. PQRMaster returns 5 tables. BudgetHeader returns 4
tables. The signal is inverse to the need.

The result for a detail table carries little information. PQRMaster returns its
own detail tables. A reader gets the same answer from the table name prefix.

The ADR states that it supersedes design decision 9 in the integration design
document. That decision set the default cascade depth to 1.

The ADR states that ADR-0011 keeps its original text. ADR-0011 cites the
resolver function as evidence that a live query fallback could not run. The
function is now gone. The ADR-0031 note explains this to a later reader.

### The documents

Update the readme, the user manual, the advanced handbook and the integration
design document.

Three statements in the integration design document are already wrong. The
document says that the resolver reads the foreign key system view. The resolver
reads the SQL cache and infers from primary key names. The document says twice
that the table list includes the cascade tables. The cascade tables are a
separate field. The removal deletes all three statements.

The user manual holds two troubleshooting rows about the feature. Remove both
rows.

Design decision 9 in the integration design document keeps its original text.
That decision set the default cascade depth to 1. It is a record of an earlier
position, like the S3 milestone table beside it. ADR-0031 supersedes it, and a
reader finds the current position there.

## Testing Decisions

### What makes a good test here

A good test asserts what the product reports. A good test does not assert how
the product reached the report. This removal changes a contract, so the test
asserts the contract.

### The seam

Use one seam. The seam is the committed OpenAPI export guard in the analysis
service test suite.

That test asserts that the committed export equals the schema that the live
application produces. The schema change removes the depth field from two
requests and the cascade field from one response. The test fails until the
developer regenerates the export. One seam covers the whole contract change.

### Prior art

The OpenAPI export guard is the prior art for a contract test in this
repository. It already guards the analyze route, the refresh route and the path
evidence route.

### Existing tests to change

Remove the dedicated resolver test file. It holds four tests. All four test the
removed module.

Remove the depth argument from the test cases that pass it. Nine test cases in
the analysis service pass a depth value.

One test case uses a depth of 2 as a sample of a field outside a scope. Remove
that one argument. The other fields in the same test still cover the behaviour.

Two orchestrator test files build a program payload with the cascade field.
Remove the field from the payloads. One assertion checks the cascade field
value as a marker for the correct cache. The same test already checks the
stored procedure names as a marker for the same fact. Remove the cascade
assertion. The coverage stays.

### Acceptance

The whole test suite passes in both repositories after the removal. No new test
is needed.

## Out of Scope

Real foreign key support is out of scope. That work needs four steps. The
scanner must collect the foreign key system view. Every system must run a new
SQL cache refresh. The resolver must read real foreign keys. A database
administrator must declare real foreign key constraints. The user decided that
the cascade table is not a wanted output, so this work has no value now.

A rewrite of ADR-0011 is out of scope. The record keeps its original text.

A rewrite of the S3 milestone table is out of scope. The table records what the
team built, and that record is correct.

A rewrite of design decision 9 is out of scope. ADR-0031 supersedes it in
place.

A change to the reverse lookup by table name is out of scope. That endpoint
never used this feature.

A change to the cross program expansion depth is out of scope. That is a
different setting with a different purpose.

## Further Notes

The measurements in this spec come from the live SQL caches on disk. The probe
called the real adjacency builder and the real breadth first search from the
resolver module.

The cascade output holds obvious noise today. The result for the PUR database
includes two SQL Server system tables and one dated backup table. The result
also includes many temporary tables and work tables.

The user confirmed five decisions during the interview. The cascade table is
not a wanted output. The removal is complete, not a configuration change. A new
ADR records the decision. The response field is removed directly. The
historical records keep their original text. This spec carries all five
decisions without change.
