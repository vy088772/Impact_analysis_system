# One SQL Cache Holds One Database

**Status:** Accepted
**Date:** 2026-09-29

## Context

[ADR-0009](0009-sql-cache-identity-decoupled-from-system.md) named one SQL cache by the triple `(server, database, schema)`. The refresh asked SQL Server for one schema at a time, and the schema defaulted to `dbo`. The cache payload held one cache-wide `schema` field. No object in the cache carried a schema of its own.

A Database with tables in `COMMON` and `HR` therefore produced a `dbo` cache that held neither. The analyst received an empty answer and no warning that the question never reached those schemas.

A stored procedure often reads a table in another schema of its own Database. The SQL Execution Graph of one schema cache records that reference. No cache could resolve it, because the one cache that holds the other schema is a different file with a different identity.

## Decision

One SQL cache holds one Database and every schema inside it. Each object in the cache carries its own schema.

- The SQL Cache Identity drops its schema part and becomes the normalized pair `(server, database)`. The cache filename follows: `{server}__{database}.json`.
- The refresh lists every object kind of every schema in one query. It keeps the excluded-schema rule in one filter over the returned rows.
- The refresh CLI loses its schema option. A refresh covers the whole Database or fails.
- The `db_schema` field leaves the refresh request, the refresh response, the Scan Record, and the `/scan_records` response.
- The cache-wide `schema` field leaves the payload. Each object states its own `schema`.
- The SQL cache format version rises to 11. Every cache written under a three-part filename never loads again.

## Rejected alternative

**Keep one cache per schema.** The cache format cannot record which schema an object belongs to, because the schema is a property of the whole file. A cross-schema reference in the SQL Execution Graph then has no cache that can resolve it. The operator must also know every schema of every Database before a refresh. A schema that nobody names stays empty with no warning. The caller's catalog declares a (System, Database) pair and states no schema, so the caller cannot know which schema caches to open.

## Consequences

- An operator runs one refresh per Database, not one per schema.
- No migration tool exists. A migration needs the schema of each object, and an old cache does not hold that fact. Every Database needs one operator refresh after the format version rise.
- The old three-part files stay on disk beside the new files. No reader finds them, and no cleanup step removes them.
- A name comparison can no longer read the schema from the cache identity. It reads the schema from the object. The Canonical Object Identity module keeps that schema, and the two-bucket rule decides a lookup. See [ADR-0034](0034-the-object-location-index-states-its-own-format-version.md) and [ADR-0035](0035-an-unproven-schema-marks-one-execution-path.md).
- ADR-0009 stays valid for the server rule and the System independence. Only its schema part changes.
