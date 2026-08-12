# Use an AST-backed SQL Execution Graph

Replace the cache's untyped `dependencies` / `depends_on` / `depended_by` model with one AST-backed SQL Execution Graph. The old model mixes object types and lacks DML order, branches, and write columns; the new graph is the only source for SQL flow and reverse lookup, while unresolved dynamic SQL remains explicit rather than guessed.

## Consequences

Existing SQL caches are intentionally incompatible and must be rebuilt with `refresh_sql_cli`. The graph must cover stored procedures, views, functions, tables, explicit SP calls, DML operations, and unresolved dynamic-SQL operations.