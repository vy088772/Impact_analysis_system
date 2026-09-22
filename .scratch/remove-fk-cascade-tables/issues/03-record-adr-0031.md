# 03 — Record ADR-0031

**What to build:** A maintainer who asks why this repository has no cascade
table report finds one document that answers it. The document also stops a later
developer from building the same feature again.

Add ADR-0031 to the decision record directory. Write it in English, to match the
other records there.

State the decision. The primary key naming inference is not sufficient for a
cascade table report. The feature is removed.

State the reasons, with the measurements that the spec holds.

The SQL cache holds no foreign key data. A cached table object holds three
fields only: the name, the columns and the primary keys.

A primary key does not describe a relation. A primary key states that a column
identifies a row in its own table. It names no other table. A foreign key names
the other table. The databases declare primary keys only, so the inference had
no structural base.

The primary key coverage is partial. One database holds 401 tables. 216 tables
have a primary key, and 128 tables have a single primary key. The resolver
skipped a compound primary key, so 32 percent of the tables could start an
inference. The other databases measured 72, 32, 100 and 0 percent.

The inference failed on a master table. The adjacency for that database had 247
nodes and 346 edges, and the largest fan-out was 65. A depth of 1 from the
largest node returned 50 tables, which was the cap. A depth of 2 returned the
same 50 tables.

A filter did not rescue the inference. A filter that removed the temporary
tables, the work tables, the backup tables, the log tables and the system tables
gave 0 tables for each of the three largest master tables. The same filter gave
5 and 4 tables for two detail tables. The signal was inverse to the need.

State what the record supersedes and what it leaves alone. ADR-0031 supersedes
design decision 9 in the integration design document, which set the default
cascade depth to 1. ADR-0011 keeps its original text, and so does design
decision 9 and the S3 milestone table beside it. Note that ADR-0011 cites the
resolver function as evidence that a live query fallback could not run, and that
the function is now gone.

**Blocked by:** 01 — Remove the FK cascade table from the analysis service; 02 —
Remove the FK cascade table from the orchestrator. The record states that the
resolver is gone. It must not land before that is true.

**Status:** ready-for-agent

- [ ] ADR-0031 exists in the decision record directory, and it is written in English.
- [ ] The record states the decision and every measurement listed above.
- [ ] The record names design decision 9 as the decision it supersedes.
- [ ] The record notes that ADR-0011 now cites a function that no longer exists.
- [ ] ADR-0011 is unchanged.
