"""CSharpAnalysisGateway: evidence-rated Database Invocations from direct SqlClient use.

Combines raw Roslyn facts (from StaticAnalyzerHost) with a database-scoped SP Catalog
and connection-source resolution. Roslyn only reports what the source contains; all
evidence-rating decisions live here so unresolved names or databases are never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Set


class InvocationEvidence(Enum):
    """Confidence level of a detected Database Invocation."""

    PROVEN = "proven"
    LIKELY = "likely"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class InvocationSourceSpan:
    """Identifies the source snapshot region backing one Database Invocation."""

    relative_path: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class DbInvocation:
    """One evidence-rated Database Invocation produced by the gateway."""

    class_name: str
    method_name: str
    database: Optional[str]
    procedure_name: Optional[str]
    evidence: InvocationEvidence
    source: InvocationSourceSpan
    reason: str = ""


def normalize_procedure_name(raw_name: str) -> str:
    """Normalize a candidate SP name to its bare, case-insensitive identity."""
    cleaned = raw_name.strip().replace("[", "").replace("]", "")
    bare = cleaned.split(".")[-1]
    return bare.strip().lower()


@dataclass(frozen=True)
class SpCatalog:
    """Database-scoped set of normalized stored procedure identities."""

    procedures_by_database: Dict[str, Set[str]]

    @classmethod
    def from_databases(cls, procedures_by_database: Dict[str, Iterable[str]]) -> "SpCatalog":
        return cls({
            database: {normalize_procedure_name(name) for name in names}
            for database, names in procedures_by_database.items()
        })

    def contains(self, database: str, normalized_name: str) -> bool:
        return normalized_name in self.procedures_by_database.get(database, set())

    def databases_containing(self, normalized_name: str) -> List[str]:
        return sorted(
            database
            for database, names in self.procedures_by_database.items()
            if normalized_name in names
        )


class CSharpAnalysisGateway:
    """Validates direct SqlClient invocations against a database-scoped SP Catalog."""

    def __init__(self, catalog: SpCatalog, connection_sources: Optional[Dict[str, str]] = None):
        self._catalog = catalog
        self._connection_sources = connection_sources or {}

    def resolve_direct_invocations(self, relative_path: str, raw_invocations: List[dict]) -> List[DbInvocation]:
        """Turn raw Roslyn direct-SqlClient facts into evidence-rated Database Invocations."""
        results: List[DbInvocation] = []
        for raw in raw_invocations:
            invocation = self._resolve_one(relative_path, raw)
            if invocation is not None:
                results.append(invocation)
        return results

    def _resolve_one(self, relative_path: str, raw: dict) -> Optional[DbInvocation]:
        if not raw.get("command_type_stored_procedure"):
            # No explicit StoredProcedure command type: this is plain SQL text, not an SP invocation.
            return None

        source = InvocationSourceSpan(relative_path, raw["start_offset"], raw["end_offset"])
        class_name = raw["class_name"]
        method_name = raw["method_name"]

        connection_expression = raw.get("connection_expression")
        database = self._connection_sources.get(connection_expression) if connection_expression else None

        if raw.get("command_text_kind") != "literal" or not raw.get("command_text"):
            return DbInvocation(
                class_name, method_name, database, None, InvocationEvidence.UNRESOLVED, source, "dynamic_command_text"
            )

        normalized_name = normalize_procedure_name(raw["command_text"])

        if database:
            if self._catalog.contains(database, normalized_name):
                return DbInvocation(class_name, method_name, database, normalized_name, InvocationEvidence.PROVEN, source)
            return DbInvocation(
                class_name, method_name, database, normalized_name, InvocationEvidence.UNRESOLVED, source,
                "not_in_resolved_catalog",
            )

        matches = self._catalog.databases_containing(normalized_name)
        if len(matches) == 1:
            return DbInvocation(
                class_name, method_name, matches[0], normalized_name, InvocationEvidence.LIKELY, source,
                "unique_across_catalogs",
            )
        if len(matches) == 0:
            return DbInvocation(
                class_name, method_name, None, normalized_name, InvocationEvidence.UNRESOLVED, source,
                "unknown_database_source",
            )
        return DbInvocation(
            class_name, method_name, None, normalized_name, InvocationEvidence.UNRESOLVED, source,
            "ambiguous_cross_database",
        )
