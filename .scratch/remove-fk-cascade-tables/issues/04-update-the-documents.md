# 04 — Update the documents

**What to build:** A reader of the documents finds no description of a FK
cascade table. A reader does not look for a feature that is not there, and does
not build a client against a field that the service no longer returns.

Update the readme, the user manual, the advanced handbook and the integration
design document.

Three statements in the integration design document are already wrong today.
The document says that the resolver reads the foreign key system view. The
resolver read the SQL cache and inferred from primary key names. The document
says twice that the table list includes the cascade tables. The cascade tables
were a separate field. Delete all three statements with the rest.

The user manual holds two troubleshooting rows about the feature. One row tells
the reader to refresh the cache when the cascade list shrinks. The other row
tells the reader that an empty cascade list is normal. Remove both rows.

The advanced handbook names the resolver module in its module list, and shows a
cascade depth in a sample configuration. Remove both.

Leave the historical records alone. Design decision 9 keeps its original text,
because ADR-0031 supersedes it in place. The S3 milestone table keeps its
original text, because it records what the team built and that record is
correct.

**Blocked by:** 01 — Remove the FK cascade table from the analysis service; 02 —
Remove the FK cascade table from the orchestrator. The documents describe the
real behaviour of both repositories.

**Status:** ready-for-agent

- [ ] The readme feature list names no cascade table.
- [ ] The user manual holds neither troubleshooting row.
- [ ] The advanced handbook module list names no resolver module, and its sample configuration shows no cascade depth.
- [ ] The integration design document describes the real response fields, and holds none of the three wrong statements.
- [ ] Design decision 9 is unchanged.
- [ ] The S3 milestone table is unchanged.
