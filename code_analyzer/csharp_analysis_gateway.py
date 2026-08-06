"""CSharpAnalysisGateway: evidence-rated Database Invocations from direct SqlClient use.

Combines raw Roslyn facts (from StaticAnalyzerHost) with a database-scoped SP Catalog
and connection-source resolution. Roslyn only reports what the source contains; all
evidence-rating decisions live here so unresolved names or databases are never guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set


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
    procedure_schema: Optional[str] = None
    method_chain: tuple[str, ...] = ()
    branch_context: tuple[str, ...] = ()
    source_snapshot_hash: str = ""
    method_class_chain: tuple[str, ...] = ()
    database_candidates: tuple[str, ...] = ()
    raw_command_text: Optional[str] = None
    external_wrapper_method: str = ""
    wrapper_contract: str = ""
    wrapper_contract_source: str = ""
    wrapper_receiver_type: str = ""
    wrapper_contract_candidates: tuple[str, ...] = ()


def _load_external_wrapper_contracts() -> Dict[str, Dict[str, Any]]:
    """Load the repository-level external wrapper contract registry."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "external_wrapper_contracts.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    contracts = payload.get("contracts", {})
    if not isinstance(contracts, dict):
        return {}
    loaded_contracts: Dict[str, Dict[str, Any]] = {}
    for name, contract in contracts.items():
        if not isinstance(contract, dict):
            continue
        loaded = dict(contract)
        loaded["name"] = str(name)
        loaded_contracts[str(name)] = loaded
    return loaded_contracts


def load_external_wrapper_contract(contract_name: str) -> Optional[Dict[str, Any]]:
    """Load one named external wrapper contract from repository configuration."""
    normalized_name = str(contract_name or "").strip().casefold()
    if not normalized_name:
        return None
    return next(
        (
            contract
            for name, contract in _load_external_wrapper_contracts().items()
            if name.casefold() == normalized_name
        ),
        None,
    )


def external_wrapper_contract_candidates(
    receiver_type: str,
) -> List[Dict[str, Any]]:
    """Return auto-selectable contracts matching one receiver type."""
    normalized_receiver = str(receiver_type or "").strip().split(".")[-1].casefold()
    if not normalized_receiver:
        return []

    candidates = []
    for contract in _load_external_wrapper_contracts().values():
        if contract.get("auto_select") is not True:
            continue
        receiver_types = contract.get("receiver_types", [])
        if not isinstance(receiver_types, list):
            continue
        if any(
            normalized_receiver == str(candidate).split(".")[-1].casefold()
            for candidate in receiver_types
        ):
            candidates.append(contract)
    return candidates


def load_external_wrapper_contract_for_receiver(
    receiver_type: str,
) -> Optional[Dict[str, Any]]:
    """Auto-select one contract when a receiver type identifies it uniquely.

    Automatic selection is intentionally conservative: contracts must opt in with
    ``auto_select`` and exactly one contract may match the receiver type.
    """
    candidates = external_wrapper_contract_candidates(receiver_type)
    return candidates[0] if len(candidates) == 1 else None


def normalize_procedure_name(raw_name: str) -> str:
    """Normalize a candidate SP name to its bare, case-insensitive identity."""
    cleaned = raw_name.strip().replace("[", "").replace("]", "")
    bare = cleaned.split(".")[-1]
    return bare.strip().lower()


@dataclass(frozen=True)
class SpCatalog:
    """Database-scoped set of normalized stored procedure identities."""

    procedures_by_database: Dict[str, Set[str]]
    qualified_procedures_by_database: Dict[str, Set[str]] = field(default_factory=dict)

    @classmethod
    def from_databases(
        cls,
        procedures_by_database: Dict[str, Iterable[str]],
        default_schema: Optional[str] = "dbo",
    ) -> "SpCatalog":
        bare_names: Dict[str, Set[str]] = {}
        qualified_names: Dict[str, Set[str]] = {}
        canonical_databases: Dict[str, str] = {}
        normalized_default_schema = normalize_schema_name(default_schema or "")
        for database, names in procedures_by_database.items():
            database_name = str(database).strip()
            database_key = database_name.casefold()
            canonical_database = canonical_databases.setdefault(database_key, database_name)
            bare_names.setdefault(canonical_database, set())
            qualified_names.setdefault(canonical_database, set())
            for name in names:
                normalized_name = normalize_procedure_name(name)
                bare_names[canonical_database].add(normalized_name)
                schema = normalize_procedure_schema(name)
                schema = schema or normalized_default_schema
                if schema:
                    qualified_names[canonical_database].add(f"{schema}.{normalized_name}")
        return cls(bare_names, qualified_names)

    def contains(
        self,
        database: str,
        normalized_name: str,
        schema: Optional[str] = None,
    ) -> bool:
        database_key = self._database_key(database)
        bare_names = self.procedures_by_database.get(database_key, set())
        if not schema:
            return normalized_name in bare_names
        qualified_names = self.qualified_procedures_by_database.get(database_key, set())
        qualified_identity = f"{schema}.{normalized_name}"
        return qualified_identity in qualified_names

    def databases_containing(
        self,
        normalized_name: str,
        schema: Optional[str] = None,
    ) -> List[str]:
        return sorted(
            database
            for database, names in self.procedures_by_database.items()
            if self.contains(database, normalized_name, schema)
        )

    def _database_key(self, database: str) -> str:
        if database in self.procedures_by_database:
            return database
        folded = database.casefold()
        return next(
            (candidate for candidate in self.procedures_by_database if candidate.casefold() == folded),
            database,
        )


class CSharpAnalysisGateway:
    """Validates direct SqlClient invocations against a database-scoped SP Catalog."""

    def __init__(
        self,
        catalog: SpCatalog,
        connection_sources: Optional[Dict[str, str]] = None,
        external_wrapper_contract: Optional[Mapping[str, Any]] = None,
    ):
        self._catalog = catalog
        self._connection_sources = connection_sources or {}
        self._external_wrapper_contract = dict(external_wrapper_contract or {})
        self._wrapper_contract_name = str(self._external_wrapper_contract.get("name") or "")

    def resolve_direct_invocations(self, relative_path: str, raw_invocations: List[dict]) -> List[DbInvocation]:
        """Turn raw Roslyn direct-SqlClient facts into evidence-rated Database Invocations."""
        results: List[DbInvocation] = []
        for raw in raw_invocations:
            invocation = self._resolve_one(relative_path, raw)
            if invocation is not None:
                results.append(invocation)
        return results

    def _resolve_one(self, relative_path: str, raw: dict) -> Optional[DbInvocation]:
        invocation_kind = str(raw.get("invocation_kind") or "").casefold()
        if invocation_kind == "source_wrapper":
            return self._resolve_wrapper_invocation(relative_path, raw)
        if invocation_kind in {"dapper", "entity_framework", "entityframework", "ef"}:
            return self._resolve_adapter_invocation(relative_path, raw)

        if not raw.get("command_type_stored_procedure"):
            # No explicit StoredProcedure command type: this is plain SQL text, not an SP invocation.
            return None

        source = InvocationSourceSpan(relative_path, raw["start_offset"], raw["end_offset"])
        class_name = raw["class_name"]
        method_name = raw["method_name"]
        branch_context = self._branch_context(raw)

        connection_expression = raw.get("connection_expression")
        database = self._resolve_database(connection_expression)

        if raw.get("command_text_kind") != "literal" or not raw.get("command_text"):
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "dynamic_command_text",
                branch_context=branch_context,
            )

        return self._rate_literal_candidate(
            class_name,
            method_name,
            database,
            raw["command_text"],
            source,
            branch_context=branch_context,
        )

    def _resolve_adapter_invocation(self, relative_path: str, raw: dict) -> Optional[DbInvocation]:
        mode = str(raw.get("adapter_mode") or raw.get("wrapper_mode") or "").casefold()
        if mode == "inline_sql":
            return None

        source = InvocationSourceSpan(relative_path, raw["start_offset"], raw["end_offset"])
        class_name = raw["class_name"]
        method_name = raw["method_name"]
        branch_context = self._branch_context(raw)
        database = self._resolve_database(raw.get("connection_expression"))
        if mode != "stored_procedure" and raw.get("command_type_stored_procedure") is not True:
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "adapter_mode_unresolved",
                method_chain=tuple(raw.get("method_chain") or ()),
                branch_context=branch_context,
            )
        if raw.get("command_text_kind") != "literal" or not raw.get("command_text"):
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "dynamic_command_text",
                method_chain=tuple(raw.get("method_chain") or ()),
                branch_context=branch_context,
            )
        return self._rate_literal_candidate(
            class_name,
            method_name,
            database,
            raw["command_text"],
            source,
            method_chain=tuple(raw.get("method_chain") or ()),
            branch_context=branch_context,
        )

    def _resolve_wrapper_invocation(self, relative_path: str, raw: dict) -> Optional[DbInvocation]:
        mode = str(raw.get("wrapper_mode") or "").casefold()
        if mode == "inline_sql":
            return None

        source = InvocationSourceSpan(relative_path, raw["start_offset"], raw["end_offset"])
        class_name = raw["class_name"]
        method_name = raw["method_name"]
        branch_context = self._branch_context(raw)
        method_class_chain = tuple(
            value
            for value in (class_name, raw.get("wrapper_class_name"))
            if value
        )
        database = self._resolve_database(raw.get("connection_expression"))
        (
            external_contract,
            wrapper_contract_source,
            wrapper_contract_candidates,
        ) = self._external_wrapper_resolution_for_raw(raw)
        if raw.get("wrapper_source_available") is True:
            wrapper_contract_source = ""
            wrapper_contract_candidates = ()
        contract_method = self._external_wrapper_method_contract(raw, external_contract)
        wrapper_receiver_type = str(raw.get("wrapper_receiver_type") or "")

        def annotate(invocation: DbInvocation) -> DbInvocation:
            return replace(
                invocation,
                wrapper_contract_source=wrapper_contract_source,
                wrapper_receiver_type=wrapper_receiver_type,
                wrapper_contract_candidates=wrapper_contract_candidates,
            )

        external_wrapper_method = (
            str(raw.get("wrapper_method_name") or "")
            if raw.get("wrapper_source_available") is not True
            else ""
        )
        wrapper_contract = (
            str(external_contract.get("name") or self._wrapper_contract_name)
            if contract_method is not None and external_contract is not None
            else ""
        )

        if raw.get("wrapper_source_available") is not True:
            if contract_method is not None:
                contract_mode = str(contract_method.get("mode") or "").casefold()
                if contract_mode == "inline_sql":
                    return None
                if contract_mode == "stored_procedure":
                    mode = "stored_procedure"
                elif contract_mode == "call_site" and mode == "inline_sql":
                    return None
                elif contract_mode == "call_site" and mode == "stored_procedure":
                    mode = "stored_procedure"
                elif mode != "stored_procedure":
                    return annotate(DbInvocation(
                        class_name,
                        method_name,
                        database,
                        None,
                        InvocationEvidence.UNRESOLVED,
                        source,
                        "wrapper_mode_unresolved",
                        method_chain=tuple(raw.get("method_chain") or ()),
                        method_class_chain=method_class_chain,
                        branch_context=branch_context,
                        external_wrapper_method=external_wrapper_method,
                        wrapper_contract=wrapper_contract,
                    ))
                if not contract_method.get("sink"):
                    return annotate(DbInvocation(
                        class_name,
                        method_name,
                        database,
                        None,
                        InvocationEvidence.UNRESOLVED,
                        source,
                        "wrapper_contract_sink_unresolved",
                        method_chain=tuple(raw.get("method_chain") or ()),
                        method_class_chain=method_class_chain,
                        branch_context=branch_context,
                        external_wrapper_method=external_wrapper_method,
                        wrapper_contract=wrapper_contract,
                    ))

                if raw.get("command_text_kind") != "literal" or not raw.get("command_text"):
                    return annotate(DbInvocation(
                        class_name,
                        method_name,
                        database,
                        None,
                        InvocationEvidence.UNRESOLVED,
                        source,
                        "dynamic_command_text",
                        method_chain=tuple(raw.get("method_chain") or ()),
                        method_class_chain=method_class_chain,
                        branch_context=branch_context,
                        external_wrapper_method=external_wrapper_method,
                        wrapper_contract=wrapper_contract,
                    ))

                rated = self._rate_literal_candidate(
                    class_name,
                    method_name,
                    database,
                    raw["command_text"],
                    source,
                    method_chain=tuple(raw.get("method_chain") or ()),
                    method_class_chain=method_class_chain,
                    branch_context=branch_context,
                )
                return annotate(replace(
                    rated,
                    external_wrapper_method=external_wrapper_method,
                    wrapper_contract=wrapper_contract,
                ))

            procedure_name = None
            procedure_schema = None
            if (
                mode == "stored_procedure"
                and raw.get("command_text_kind") == "literal"
                and raw.get("command_text")
            ):
                procedure_name = normalize_procedure_name(raw["command_text"])
                procedure_schema = normalize_procedure_schema(raw["command_text"])
            return annotate(DbInvocation(
                class_name,
                method_name,
                database,
                procedure_name,
                InvocationEvidence.UNRESOLVED,
                source,
                "wrapper_source_unavailable",
                procedure_schema,
                method_chain=tuple(raw.get("method_chain") or ()),
                method_class_chain=method_class_chain,
                branch_context=branch_context,
                raw_command_text=raw.get("command_text") if procedure_name else None,
                external_wrapper_method=external_wrapper_method,
            ))
        if raw.get("wrapper_reaches_stored_procedure_sink") is not True:
            return annotate(DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "wrapper_sink_unresolved",
                method_chain=tuple(raw.get("method_chain") or ()),
                method_class_chain=method_class_chain,
                branch_context=branch_context,
            ))
        if mode != "stored_procedure":
            return annotate(DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "wrapper_mode_unresolved",
                method_chain=tuple(raw.get("method_chain") or ()),
                method_class_chain=method_class_chain,
                branch_context=branch_context,
            ))

        if raw.get("command_text_kind") != "literal" or not raw.get("command_text"):
            return annotate(DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "dynamic_command_text",
                method_chain=tuple(raw.get("method_chain") or ()),
                method_class_chain=method_class_chain,
                branch_context=branch_context,
            ))

        return annotate(self._rate_literal_candidate(
            class_name,
            method_name,
            database,
            raw["command_text"],
            source,
            method_chain=tuple(raw.get("method_chain") or ()),
            method_class_chain=method_class_chain,
            branch_context=branch_context,
        ))

    def _external_wrapper_resolution_for_raw(
        self,
        raw: Mapping[str, Any],
    ) -> tuple[Optional[Mapping[str, Any]], str, tuple[str, ...]]:
        if self._external_wrapper_contract:
            return self._external_wrapper_contract, "explicit", ()

        receiver_type = str(raw.get("wrapper_receiver_type") or "")
        candidates = external_wrapper_contract_candidates(receiver_type)
        candidate_names = tuple(str(contract.get("name") or "") for contract in candidates)
        if len(candidates) == 1:
            return candidates[0], "auto_receiver_type", candidate_names
        if candidates:
            return None, "ambiguous_receiver_type", candidate_names
        return None, "unresolved_receiver_type", ()

    def _external_wrapper_contract_for_raw(
        self,
        raw: Mapping[str, Any],
    ) -> Optional[Mapping[str, Any]]:
        if self._external_wrapper_contract:
            return self._external_wrapper_contract
        return load_external_wrapper_contract_for_receiver(
            str(raw.get("wrapper_receiver_type") or "")
        )

    def _external_wrapper_method_contract(
        self,
        raw: Mapping[str, Any],
        contract: Optional[Mapping[str, Any]] = None,
    ) -> Optional[Mapping[str, Any]]:
        contract = contract or self._external_wrapper_contract_for_raw(raw)
        if contract is None:
            return None
        methods = contract.get("methods", {})
        if not isinstance(methods, Mapping):
            return None

        method_name = str(raw.get("wrapper_method_name") or "").casefold()
        if not method_name:
            return None
        configured_method = next(
            (
                value
                for name, value in methods.items()
                if str(name).casefold() == method_name and isinstance(value, Mapping)
            ),
            None,
        )
        if configured_method is None:
            return None

        receiver_types = contract.get("receiver_types", [])
        receiver_type = str(raw.get("wrapper_receiver_type") or "").strip()
        if receiver_type and receiver_types:
            normalized_receiver = receiver_type.split(".")[-1].casefold()
            if not any(
                normalized_receiver == str(candidate).split(".")[-1].casefold()
                for candidate in receiver_types
            ):
                return None
        return configured_method

    def _rate_literal_candidate(
        self,
        class_name: str,
        method_name: str,
        database: Optional[str],
        command_text: str,
        source: InvocationSourceSpan,
        method_chain: tuple[str, ...] = (),
        branch_context: tuple[str, ...] = (),
        method_class_chain: tuple[str, ...] = (),
    ) -> DbInvocation:
        normalized_name = normalize_procedure_name(command_text)
        procedure_schema = normalize_procedure_schema(command_text)

        if database:
            if self._catalog.contains(database, normalized_name, procedure_schema):
                return DbInvocation(
                    class_name,
                    method_name,
                    database,
                    normalized_name,
                    InvocationEvidence.PROVEN,
                    source,
                    procedure_schema=procedure_schema,
                    method_chain=method_chain,
                    branch_context=branch_context,
                    method_class_chain=method_class_chain,
                    raw_command_text=command_text,
                )
            return DbInvocation(
                class_name,
                method_name,
                database,
                normalized_name,
                InvocationEvidence.UNRESOLVED,
                source,
                "not_in_resolved_catalog",
                procedure_schema,
                method_chain,
                branch_context,
                method_class_chain=method_class_chain,
                raw_command_text=command_text,
            )

        matches = self._catalog.databases_containing(normalized_name, procedure_schema)
        if len(matches) == 1:
            return DbInvocation(
                class_name,
                method_name,
                None,
                normalized_name,
                InvocationEvidence.LIKELY,
                source,
                "unique_across_catalogs",
                procedure_schema,
                method_chain,
                branch_context,
                method_class_chain=method_class_chain,
                database_candidates=tuple(matches),
                raw_command_text=command_text,
            )
        reason = "unknown_database_source" if len(matches) == 0 else "ambiguous_cross_database"
        return DbInvocation(
            class_name,
            method_name,
            None,
            normalized_name,
            InvocationEvidence.UNRESOLVED,
            source,
            reason,
            procedure_schema,
            method_chain,
            branch_context,
            method_class_chain=method_class_chain,
            database_candidates=tuple(matches),
            raw_command_text=command_text,
        )

    def _resolve_database(self, connection_expression: object) -> Optional[str]:
        if not connection_expression:
            return None
        expression = str(connection_expression).strip()
        if not expression:
            return None
        if expression in self._connection_sources:
            database = self._connection_sources[expression]
        else:
            folded = expression.casefold()
            database = next(
                (
                    value
                    for key, value in self._connection_sources.items()
                    if str(key).casefold() == folded
                ),
                None,
            )
        if not database or str(database).strip().casefold() in {"unknown", "unresolved"}:
            return None
        return str(database).strip()

    @staticmethod
    def _branch_context(raw: dict) -> tuple[str, ...]:
        value = raw.get("branch_context")
        if value is None:
            value = raw.get("branch_path")
        if isinstance(value, str):
            value = [value]
        return tuple(str(item) for item in (value or ()) if str(item).strip())


def normalize_procedure_schema(raw_name: str) -> Optional[str]:
    """Return the explicit schema from a qualified procedure name, when present."""
    cleaned = raw_name.strip().replace("[", "").replace("]", "")
    parts = [part.strip() for part in cleaned.split(".") if part.strip()]
    if len(parts) < 2:
        return None
    return normalize_schema_name(parts[-2])


def normalize_schema_name(raw_schema: str) -> str:
    return raw_schema.strip().replace("[", "").replace("]", "").casefold()
