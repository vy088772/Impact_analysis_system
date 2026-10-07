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
  Database attribution from that rating. A relation that reads a listed View
  or Function of the request's SQL Execution Graph also reaches each table
  behind that object, by the lineage rule of the graph queries.
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
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import schema_resolution
from canonical_object_identity import ObjectName, bare_key, bare_name, full_key, part_key, schema_qualified
from code_analyzer.csharp_analysis_gateway import DbInvocation
from code_analyzer.project_scanner import INLINE_SQL_PARSED, CSharpTableRelation, ProjectScanResult

from . import sql_cache_store
from .execution_path_builder import database_attribution
from .graph_queries import LineageIndex
from .table_match import TableMatch, TableQuestion, names_another_database


@dataclass(frozen=True)
class MethodSite:
    """The source file, the method and its class that a table relation belongs to.

    `line_number` is the line of the relation. The call graph finds the node of the
    method that holds the relation by this line (ADR-0044).
    """

    file_path: str
    method_name: str
    class_name: str = ""
    line_number: int = 0


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
    # The View or the Function that a reached answer passes through, with its schema.
    # A direct answer has none.
    through: Optional[ObjectName] = None

    @property
    def access_type(self) -> str:
        """The access type of the answer.

        A direct answer keeps the access type of its relation. A reached answer is
        `READ_INDIRECT` from a parsed relation, and `UNRESOLVED` from a fallback
        relation (ADR-0015).
        """
        if self.through is None:
            return self.relation.access_type
        return "READ_INDIRECT" if self.relation.reason == INLINE_SQL_PARSED else "UNRESOLVED"

    @property
    def table_name(self) -> str:
        """The table as the answer reports it.

        A direct answer gives the parts that the source code states, joined by dots. A reached
        answer gives the node name, as the lineage record of an Execution Path does.
        """
        if self.through is not None:
            return self.table.name
        table = self.table
        return ".".join(part for part in (table.server, table.database, table.schema, table.name) if part)

    @property
    def read_through(self) -> str:
        """The View or the Function that a reached answer passes through, as `schema.name`. Empty for a direct answer."""
        return schema_qualified(self.through) if self.through is not None else ""


def by_table(
    scan: ProjectScanResult,
    question: TableQuestion,
    rated_invocations: Sequence[DbInvocation],
    root: Path,
    graph: Optional[Mapping[str, Any]],
    sql_cache_identity: Optional[sql_cache_store.CacheIdentity],
) -> List[InlineTableAnswer]:
    """Return one answer for each relation of the scan that matches the question.

    ``rated_invocations`` are the rated Database Invocations of the scan, and ``root`` is the
    directory that their source paths count from. ``graph`` is the SQL Execution Graph of the
    request's Database. The caller gives an empty list and no graph when the request names no
    Database, because the rating and the graph exist only then. ``sql_cache_identity`` is the
    SQL Cache Identity that the request handler built, or ``None``; a connection Database with
    its name reads that cache's index.

    A relation gives its direct answer when its own object matches. When its object is a listed
    View or Function of the graph, the relation also gives one answer for each table behind that
    object that matches.
    """
    resolver = _InlineSchemaResolver(sql_cache_identity)
    rated = _rated_by_span(rated_invocations)
    lineage = _InlineLineage(graph, resolver) if graph is not None else None
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

        def answer(table: ObjectName, match: TableMatch, through: Optional[ObjectName] = None) -> InlineTableAnswer:
            return InlineTableAnswer(
                relation=relation,
                table=table,
                match=match,
                database=database,
                database_candidates=candidates,
                database_attribution=database_attribution(database, candidates),
                through=through,
            )

        table, schema_source = resolver.resolve(relation.table, database)
        match = question.match(table, database, schema_source)
        if match is not None:
            answers.append(answer(table, match))
        if lineage is not None:
            answers.extend(
                answer(reached, reached_match, through)
                for through, reached, reached_match in lineage.reached(relation.table, database, question)
            )
    return answers


def by_method(
    scan: ProjectScanResult, passes: Callable[[MethodSite], bool]
) -> List[CSharpTableRelation]:
    """Return each relation of the scan whose `MethodSite` passes the caller's test."""
    return [
        relation
        for relation in scan.table_relations
        if passes(
            MethodSite(relation.csharp_file, relation.method_name, relation.class_name, relation.line_number)
        )
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


class _InlineLineage:
    """The tables that an inline read of a View or a Function reaches in one SQL Execution Graph.

    The object of a relation names a node by the rule of the graph build: after Schema
    Resolution against the graph's Database, a stated schema and the bare name name a listed
    View or Function node. A relation of another Database names no node, because the graph
    holds no definition of that object. The reached tables come from the lineage index of the
    graph queries, so the inline answer and the Execution Path answer keep one lineage rule.
    """

    def __init__(self, graph: Mapping[str, Any], resolver: "_InlineSchemaResolver") -> None:
        self._database = str(graph.get("database") or "")
        self._resolver = resolver
        self._index = LineageIndex(graph)
        # (schema key, bare key) -> (node id, the object as the graph spells it). A listed node
        # always states its schema, so the key never holds an empty schema.
        self._nodes: Dict[tuple[str, str], tuple[str, ObjectName]] = {}
        for node in graph.get("nodes", []) or []:
            if node.get("type") not in {"view", "function"}:
                continue
            listed = ObjectName("", "", str(node.get("schema") or ""), str(node.get("name") or ""))
            self._nodes.setdefault(_node_key(listed), (str(node.get("id")), listed))

    def reached(
        self, read: ObjectName, database: str, question: TableQuestion
    ) -> List[tuple[ObjectName, ObjectName, TableMatch]]:
        """Return (the View or Function, a reached table, its match) for each reached table that matches.

        ``read`` is the object of the relation, and ``database`` is the Database of the relation.
        A relation whose Database is another Database than the graph's reaches nothing.
        """
        if names_another_database(read.database or database, self._database):
            return []
        resolved, _source = self._resolver.resolve(read, self._database)
        # An unresolved schema names no listed node, as in the graph build.
        node = self._nodes.get(_node_key(resolved)) if resolved.schema else None
        if node is None:
            return []
        node_id, through = node
        answers: List[tuple[ObjectName, ObjectName, TableMatch]] = []
        for table, schema_source in self._index.reachable_tables(node_id):
            match = question.match(table, self._database, schema_source)
            if match is not None:
                answers.append((through, table, match))
        return answers


def _node_key(name: ObjectName) -> tuple[str, str]:
    """The key of a View or Function node: the schema key and the bare key of the Canonical Object Identity."""
    return part_key(name.schema), bare_key(name)


class _InlineSchemaResolver:
    """Resolve the schema of an inline C# SQL table at question time.

    The rule is Schema Resolution outside a module: a table that states no
    schema takes `dbo` when the Object Location Index of the connection's
    Database holds `dbo.name`. The index is the only source. This class opens no
    cache, and an absent, stale, or ambiguous index leaves the schema empty.

    A connection Database with the name of the handler's SQL Cache Identity reads
    the index of that identity, so a request that names a host reads that host and
    lists no directory. Only a connection Database with another name reads the disk.
    """

    def __init__(self, sql_cache_identity: Optional[sql_cache_store.CacheIdentity]) -> None:
        self._sql_cache_identity = sql_cache_identity
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
            known = self._sql_cache_identity
            identity = (
                known
                if known is not None and known.database.casefold() == database.casefold()
                else sql_cache_store.find_cache_identity(database)
            )
            self._indexes[database] = (
                sql_cache_store.load_object_location_index(identity)
                if isinstance(identity, sql_cache_store.CacheIdentity)
                else None
            )
        return self._indexes[database]
