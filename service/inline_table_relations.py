"""The inline table relations: every rule that reads a table relation of a C# Scan Result.

A table relation is a record of stored fields. It gains no method: the code
analyzer package holds it and cannot import the service package, and the
companion repository loads it as an inert record.

The module has two queries:

- The by-table query returns one answer for each relation that matches a table
  question. `/find_by_table` and `/flow_chain` backward call it. It resolves an
  unstated schema before it matches, as Schema Resolution outside a module
  requires. It pairs a parsed relation with its rated Database Invocation by
  the source span, and takes the Database, the database candidates, and the
  Database attribution from that rating.
- The by-method query returns each relation whose `MethodSite` passes the
  caller's test. It holds no ownership rule. `/flow_chain` forward, the
  `/analyze` screen table list, and the shared component table list call it
  through `table_names_by_method`, which gives the bare table names.

Three readers apply no rule, and they read the stored fields: the relation
count of the scan statistics, the merge of scans, and the HTML report.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import schema_resolution
from canonical_object_identity import ObjectName, bare_name, full_key
from code_analyzer.csharp_analysis_gateway import DbInvocation
from code_analyzer.project_scanner import CSharpTableRelation, ProjectScanResult

from . import sql_cache_store
from .execution_path_builder import database_attribution
from .table_match import TableMatch, TableQuestion


@dataclass(frozen=True)
class MethodSite:
    """The source file and the method that a table relation belongs to."""

    file_path: str
    method_name: str


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


def by_table(
    scan: ProjectScanResult,
    question: TableQuestion,
    rated_invocations: Sequence[DbInvocation],
    root: Path,
) -> List[InlineTableAnswer]:
    """Return one answer for each relation of the scan that matches the question.

    ``rated_invocations`` are the rated Database Invocations of the scan, and ``root`` is the
    directory that their source paths count from. The caller gives an empty list when the request
    names no Database, because the rating runs only then.
    """
    resolver = _InlineSchemaResolver()
    rated = _rated_by_span(rated_invocations)
    answers: List[InlineTableAnswer] = []
    for relation in scan.table_relations:
        key = _span_key(relation.csharp_file, relation.invocation_span, root)
        invocation = rated.get(key) if key is not None else None
        if invocation is not None:
            # The rating decides the Database. A Database with candidates or with no answer
            # leaves the Database out of the match, so it never hides a program.
            database = invocation.database or ""
            candidates = tuple(invocation.database_candidates)
        else:
            # A relation with no rated invocation takes the Database that the C# parser
            # found for its connection. A connection the parser cannot resolve leaves the
            # Database out of the match. A fallback relation always takes this branch.
            database = relation.connection_database
            candidates = ()
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
                database_candidates=candidates,
                database_attribution=database_attribution(database, candidates),
            )
        )
    return answers


def by_method(
    scan: ProjectScanResult, passes: Callable[[MethodSite], bool]
) -> List[CSharpTableRelation]:
    """Return each relation of the scan whose `MethodSite` passes the caller's test."""
    return [
        relation
        for relation in scan.table_relations
        if passes(MethodSite(relation.csharp_file, relation.method_name))
    ]


def table_names_by_method(scan: ProjectScanResult, passes: Callable[[MethodSite], bool]) -> List[str]:
    """Return the bare table name of each relation that the by-method query returns.

    The names keep the order of the relations, and each name occurs once.
    """
    names: List[str] = []
    for relation in by_method(scan, passes):
        name = bare_name(relation.table)
        if name not in names:
            names.append(name)
    return names


def _span_key(file_path: str, span: Sequence[int], root: Path) -> Optional[tuple[str, int, int]]:
    """The pairing key of a relation: its source file, relative to the root, and its source span."""
    if len(span) != 2:
        return None
    try:
        relative = Path(file_path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = file_path.replace("\\", "/")
    return relative.casefold(), int(span[0]), int(span[1])


def _rated_by_span(rated_invocations: Sequence[DbInvocation]) -> Dict[tuple[str, int, int], DbInvocation]:
    """Index the rated Database Invocations by the key that a parsed relation carries."""
    rated: Dict[tuple[str, int, int], DbInvocation] = {}
    for invocation in rated_invocations:
        source = invocation.source
        key = (source.relative_path.replace("\\", "/").casefold(), source.start_offset, source.end_offset)
        rated.setdefault(key, invocation)
    return rated


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
