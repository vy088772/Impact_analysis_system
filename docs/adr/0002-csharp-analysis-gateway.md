# Use One C# Analysis Gateway for Database Invocations

Use a Roslyn-backed CSharpAnalysisGateway as the long-term source of C# method Flow and database invocation facts. It validates direct `SqlClient` and source-available wrapper calls against a database-scoped SP Catalog, records confidence and unresolved cases, and replaces the regex wrapper allowlist after a bounded comparison migration.

## Consequences

C# source snapshots are stored once per current scan root and referenced by source span; execution paths never duplicate source text. The legacy regex detector is comparison-only until representative systems satisfy the cutover gate, then it no longer produces formal relationship data.