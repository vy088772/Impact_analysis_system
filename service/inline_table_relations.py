"""The inline table relations: every rule that reads a table relation of a C# Scan Result.

A table relation is a record of stored fields. It gains no method: the code
analyzer package holds it and cannot import the service package, and the
companion repository loads it as an inert record.

The module has two queries:

- The by-table query returns one answer for each relation that matches a table
  question. It resolves an unstated schema before it matches, as Schema
  Resolution outside a module requires.
- The by-method query returns each relation whose source file and method pass
  the caller's test. It holds no ownership rule.

Three readers apply no rule, and they read the stored fields: the relation
count of the scan statistics, the merge of scans, and the HTML report.
`/flow_chain` backward still reads the relations itself. Ticket 06 of
`.scratch/inline-sql-tables-come-from-the-parser/` moves it here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional

import schema_resolution
from canonical_object_identity import ObjectName, full_key
from code_analyzer.project_scanner import CSharpTableRelation, ProjectScanResult

from . import sql_cache_store
from .execution_path_builder import database_attribution
from .table_match import TableMatch, TableQuestion


@dataclass(frozen=True)
class InlineTableAnswer:
    """One relation that answers a table question, with what the question time adds."""

    relation: CSharpTableRelation
    # The table of the relation, with its resolved schema.
    table: ObjectName
    match: TableMatch
    database: str
    database_candidates: tuple[str, ...]
    database_attribution: str


def by_table(scan: ProjectScanResult, question: TableQuestion) -> List[InlineTableAnswer]:
    """Return one answer for each relation of the scan that matches the question."""
    resolver = _InlineSchemaResolver()
    answers: List[InlineTableAnswer] = []
    for relation in scan.table_relations:
        # A relation that states no Database takes the Database of its C# connection,
        # and a connection the parser cannot resolve leaves the Database out of the match.
        database = relation.connection_database
        table, schema_source = resolver.resolve(relation.table, database)
        match = question.match(table, database, schema_source)
        if match is None:
            continue
        answers.append(
            InlineTableAnswer(
                relation=relation,
                table=table,
                match=match,
                database=database,
                database_candidates=(),
                database_attribution=database_attribution(database, ()),
            )
        )
    return answers


def by_method(
    scan: ProjectScanResult, passes: Callable[[str, str], bool]
) -> List[CSharpTableRelation]:
    """Return each relation of the scan whose source file and method name pass the caller's test."""
    return [
        relation
        for relation in scan.table_relations
        if passes(relation.csharp_file, relation.method_name)
    ]


class _InlineSchemaResolver:
    """Resolve the schema of an inline C# SQL table at question time.

    The rule is Schema Resolution outside a module: a table that states no
    schema takes `dbo` when the Object Location Index of the connection's
    Database holds `dbo.name`. The index is the only source. This class opens no
    cache, and an absent, stale, or ambiguous index leaves the schema empty.
    """

    def __init__(self) -> None:
        self._indexes: Dict[str, Optional[sql_cache_store.ObjectLocationIndex]] = {}

    def resolve(self, table: ObjectName, connection_database: Optional[str]) -> tuple[ObjectName, str]:
        """Return the table with its resolved schema, and the schema source."""
        index = self._index(connection_database) if not table.schema and connection_database else None
        schema, source = schema_resolution.resolve(table, "", self._holds(index))
        return replace(table, schema=schema), source

    @staticmethod
    def _holds(index: Optional[sql_cache_store.ObjectLocationIndex]) -> Callable[[str, str], bool]:
        """Whether the index holds one object of any kind: tables, views, procedures, and functions."""

        def holds(schema: str, name: str) -> bool:
            if index is None:
                return False
            key = full_key(ObjectName("", index.database, schema, name))
            return key in index.table_full_keys or key in index.stored_procedure_full_keys

        return holds

    def _index(self, database: str) -> Optional[sql_cache_store.ObjectLocationIndex]:
        if database not in self._indexes:
            identity = sql_cache_store.find_cache_identity(database)
            self._indexes[database] = (
                sql_cache_store.load_object_location_index(identity)
                if isinstance(identity, sql_cache_store.CacheIdentity)
                else None
            )
        return self._indexes[database]
