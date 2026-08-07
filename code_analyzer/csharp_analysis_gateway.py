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
class WrapperReconciliation:
    """Deterministic classification of one raw wrapper invocation fact."""

    wrapper_kind: str
    status: str
    selection_source: str
    contract: str
    contract_mode: str
    contract_sink: str
    candidate_contracts: tuple[str, ...]
    receiver_type: str
    wrapper_method: str
    source_span: InvocationSourceSpan
    source_available: bool
    scan_root: str = ""
    reason: str = ""
    review_candidate: bool = False
    stored_procedure_mode: bool = False
    mode_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return the machine-readable boundary shape used by audit consumers."""
        return {
            "wrapper_kind": self.wrapper_kind,
            "status": self.status,
            "selection_source": self.selection_source,
            "contract": self.contract,
            "contract_mode": self.contract_mode,
            "contract_sink": self.contract_sink,
            "candidate_contracts": list(self.candidate_contracts),
            "receiver_type": self.receiver_type,
            "wrapper_method": self.wrapper_method,
            "source_available": self.source_available,
            "scan_root": self.scan_root,
            "source_span": {
                "relative_path": self.source_span.relative_path,
                "start_offset": self.source_span.start_offset,
                "end_offset": self.source_span.end_offset,
            },
            "reason": self.reason,
            "review_candidate": self.review_candidate,
            "stored_procedure_mode": self.stored_procedure_mode,
            "mode_reason": self.mode_reason,
        }


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
    wrapper_kind: str = ""
    wrapper_status: str = ""
    wrapper_selection_source: str = ""
    wrapper_contract_mode: str = ""
    wrapper_contract_sink: str = ""
    wrapper_scan_root: str = ""
    wrapper_review_candidate: bool = False
    wrapper_unresolved_reason: str = ""
    wrapper_mode_reason: str = ""
    wrapper_method: str = ""

    @property
    def wrapper_classification_status(self) -> str:
        """Compatibility alias for consumers that use the longer field name."""
        return self.wrapper_status


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


def _wrapper_contract_method(
    contract: Optional[Mapping[str, Any]],
    method_name: str,
) -> Optional[Mapping[str, Any]]:
    if contract is None:
        return None
    methods = contract.get("methods", {})
    if not isinstance(methods, Mapping):
        return None
    folded_name = str(method_name or "").casefold()
    if not folded_name:
        return None
    return next(
        (
            value
            for name, value in methods.items()
            if str(name).casefold() == folded_name and isinstance(value, Mapping)
        ),
        None,
    )


def _wrapper_contract_receiver_matches(
    contract: Mapping[str, Any],
    receiver_type: str,
) -> bool:
    receiver_types = contract.get("receiver_types", [])
    if not receiver_type or not receiver_types:
        return True
    if not isinstance(receiver_types, (list, tuple, set)):
        return False
    normalized_receiver = receiver_type.split(".")[-1].casefold()
    return any(
        normalized_receiver == str(candidate).split(".")[-1].casefold()
        for candidate in receiver_types
    )


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

    def reconcile_wrapper(
        self,
        relative_path: str,
        raw: Mapping[str, Any],
        *,
        scan_root: str = "",
        source_wrapper_available: Optional[bool] = None,
        explicit_contract: Optional[Mapping[str, Any] | str] = None,
        receiver_type_contract_candidates: Optional[Iterable[Mapping[str, Any]]] = None,
    ) -> WrapperReconciliation:
        """Classify one raw wrapper fact before rating its database evidence.

        This is the single contract/source boundary shared by Gateway consumers.
        Contract selection is deliberately separate from the later SP Catalog
        check: a selected contract does not by itself prove a procedure exists.
        """
        receiver_type = str(raw.get("wrapper_receiver_type") or "").strip()
        wrapper_method = str(raw.get("wrapper_method_name") or "").strip()
        source_available = (
            raw.get("wrapper_source_available") is True
            if source_wrapper_available is None
            else bool(source_wrapper_available)
        )
        source = InvocationSourceSpan(
            str(relative_path or raw.get("relative_path") or raw.get("source_file") or ""),
            int(raw.get("start_offset") or 0),
            int(raw.get("end_offset") or 0),
        )
        raw_mode = str(raw.get("wrapper_mode") or "").strip().casefold()
        root = str(scan_root or "")

        def result(
            *,
            wrapper_kind: str,
            status: str,
            selection_source: str,
            contract: str = "",
            contract_mode: str = "",
            contract_sink: str = "",
            candidate_contracts: Iterable[str] = (),
            reason: str = "",
            review_candidate: bool = False,
            stored_procedure_mode: bool = False,
            mode_reason: str = "",
        ) -> WrapperReconciliation:
            return WrapperReconciliation(
                wrapper_kind=wrapper_kind,
                status=status,
                selection_source=selection_source,
                contract=contract,
                contract_mode=contract_mode,
                contract_sink=contract_sink,
                candidate_contracts=tuple(
                    name for name in (str(item).strip() for item in candidate_contracts) if name
                ),
                receiver_type=receiver_type,
                wrapper_method=wrapper_method,
                source_span=source,
                source_available=source_available,
                scan_root=root,
                reason=reason,
                review_candidate=review_candidate,
                stored_procedure_mode=stored_procedure_mode,
                mode_reason=mode_reason,
            )

        def source_mode() -> tuple[bool, str]:
            if raw_mode == "inline_sql":
                return False, "inline_sql"
            if raw_mode == "stored_procedure":
                return True, ""
            return False, "wrapper_mode_unresolved"

        if source_available:
            stored_procedure_mode, mode_reason = source_mode()
            return result(
                wrapper_kind="source_wrapper",
                status="source_wrapper",
                selection_source="source_code",
                contract_mode=str(raw.get("wrapper_mode") or ""),
                stored_procedure_mode=stored_procedure_mode,
                mode_reason=mode_reason,
            )

        explicit_name = ""
        explicit_selected = False
        selected_contract: Optional[Mapping[str, Any]] = None
        if explicit_contract is None:
            selected_contract = self._external_wrapper_contract or None
            explicit_name = self._wrapper_contract_name
            explicit_selected = selected_contract is not None
        elif isinstance(explicit_contract, str):
            explicit_name = explicit_contract.strip()
            explicit_selected = bool(explicit_name)
            selected_contract = load_external_wrapper_contract(explicit_name)
        elif isinstance(explicit_contract, Mapping):
            selected_contract = explicit_contract
            explicit_name = str(explicit_contract.get("name") or "").strip()
            explicit_selected = True

        attempted_sp_mode = raw_mode == "stored_procedure"
        if explicit_selected and selected_contract is None:
            return result(
                wrapper_kind="external_wrapper",
                status="unresolved_contract",
                selection_source="explicit",
                candidate_contracts=(explicit_name,),
                reason="configured_contract_not_found",
                review_candidate=True,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
            )

        if explicit_selected:
            candidates = [
                candidate
                for candidate in (selected_contract,)
                if candidate is not None
            ]
            selection_source = "explicit"
        elif receiver_type_contract_candidates is None:
            candidates = list(external_wrapper_contract_candidates(receiver_type))
            selection_source = "auto_receiver_type"
        else:
            candidates = [
                candidate
                for candidate in receiver_type_contract_candidates
                if isinstance(candidate, Mapping)
            ]
            selection_source = "auto_receiver_type"

        candidate_names = tuple(
            str(candidate.get("name") or "").strip()
            for candidate in candidates
            if str(candidate.get("name") or "").strip()
        )
        if len(candidates) > 1:
            return result(
                wrapper_kind="external_wrapper",
                status="ambiguous_contract",
                selection_source="ambiguous_receiver_type",
                candidate_contracts=candidate_names,
                reason="multiple_contracts_match_receiver_type",
                review_candidate=True,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
            )
        if not candidates:
            return result(
                wrapper_kind="external_wrapper",
                status="unresolved_contract",
                selection_source="unresolved_receiver_type",
                reason=(
                    "receiver_type_missing"
                    if not receiver_type
                    else "no_contract_matches_receiver_type"
                ),
                review_candidate=True,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
            )

        contract = candidates[0]
        contract_name = str(contract.get("name") or explicit_name).strip()
        if not _wrapper_contract_receiver_matches(contract, receiver_type):
            return result(
                wrapper_kind="external_wrapper",
                status="receiver_mismatch",
                selection_source=selection_source,
                contract=contract_name,
                candidate_contracts=candidate_names,
                reason="receiver_type_does_not_match_contract",
                review_candidate=True,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
            )

        method_contract = _wrapper_contract_method(contract, wrapper_method)
        if method_contract is None:
            return result(
                wrapper_kind="external_wrapper",
                status="unresolved_method",
                selection_source=selection_source,
                contract=contract_name,
                candidate_contracts=candidate_names,
                reason="method_not_in_contract",
                review_candidate=True,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
            )

        contract_mode = str(method_contract.get("mode") or "")
        contract_mode_key = contract_mode.casefold()
        if raw_mode == "inline_sql" or contract_mode_key == "inline_sql":
            stored_procedure_mode = False
            mode_reason = "inline_sql"
        elif contract_mode_key == "stored_procedure":
            stored_procedure_mode = True
            mode_reason = ""
        elif contract_mode_key == "call_site" and raw_mode == "stored_procedure":
            stored_procedure_mode = True
            mode_reason = ""
        elif contract_mode_key == "call_site":
            stored_procedure_mode = False
            mode_reason = "call_site_requires_explicit_stored_procedure_mode"
        else:
            stored_procedure_mode = False
            mode_reason = "wrapper_mode_unresolved"

        return result(
            wrapper_kind="external_wrapper",
            status="explicit_selected" if explicit_selected else "auto_selected",
            selection_source=selection_source,
            contract=contract_name,
            contract_mode=contract_mode,
            contract_sink=str(method_contract.get("sink") or ""),
            candidate_contracts=candidate_names,
            stored_procedure_mode=stored_procedure_mode,
            mode_reason=mode_reason,
        )

    def resolve_direct_invocations(
        self,
        relative_path: str,
        raw_invocations: List[dict],
        *,
        scan_root: str = "",
    ) -> List[DbInvocation]:
        """Turn raw Roslyn direct-SqlClient facts into evidence-rated Database Invocations."""
        results: List[DbInvocation] = []
        for raw in raw_invocations:
            invocation = self._resolve_one(relative_path, raw, scan_root=scan_root)
            if invocation is not None:
                results.append(invocation)
        return results

    def _resolve_one(
        self,
        relative_path: str,
        raw: dict,
        *,
        scan_root: str = "",
    ) -> Optional[DbInvocation]:
        invocation_kind = str(raw.get("invocation_kind") or "").casefold()
        if invocation_kind == "source_wrapper":
            return self._resolve_wrapper_invocation(relative_path, raw, scan_root=scan_root)
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

    def _resolve_wrapper_invocation(
        self,
        relative_path: str,
        raw: dict,
        *,
        scan_root: str = "",
    ) -> Optional[DbInvocation]:
        reconciliation = self.reconcile_wrapper(
            relative_path,
            raw,
            scan_root=scan_root,
        )
        mode = str(raw.get("wrapper_mode") or "").casefold()
        if mode == "inline_sql" or reconciliation.mode_reason == "inline_sql":
            return None

        source = reconciliation.source_span
        class_name = raw["class_name"]
        method_name = raw["method_name"]
        branch_context = self._branch_context(raw)
        method_class_chain = tuple(
            value
            for value in (class_name, raw.get("wrapper_class_name"))
            if value
        )
        database = self._resolve_database(raw.get("connection_expression"))
        source_available = reconciliation.source_available
        external_wrapper_method = (
            reconciliation.wrapper_method if not source_available else ""
        )

        def annotate(invocation: DbInvocation) -> DbInvocation:
            return replace(
                invocation,
                wrapper_kind=reconciliation.wrapper_kind,
                wrapper_status=reconciliation.status,
                wrapper_selection_source=reconciliation.selection_source,
                wrapper_contract=reconciliation.contract,
                wrapper_contract_source=(
                    "" if source_available else reconciliation.selection_source
                ),
                wrapper_contract_mode=reconciliation.contract_mode,
                wrapper_contract_sink=reconciliation.contract_sink,
                wrapper_receiver_type=reconciliation.receiver_type,
                wrapper_contract_candidates=reconciliation.candidate_contracts,
                wrapper_scan_root=reconciliation.scan_root,
                wrapper_review_candidate=reconciliation.review_candidate,
                wrapper_unresolved_reason=reconciliation.reason,
                wrapper_mode_reason=reconciliation.mode_reason,
                wrapper_method=reconciliation.wrapper_method,
                external_wrapper_method=external_wrapper_method,
            )

        common = {
            "method_chain": tuple(raw.get("method_chain") or ()),
            "method_class_chain": method_class_chain,
            "branch_context": branch_context,
        }

        if not source_available:
            if reconciliation.status in {"explicit_selected", "auto_selected"}:
                if not reconciliation.contract_sink:
                    return annotate(DbInvocation(
                        class_name,
                        method_name,
                        database,
                        None,
                        InvocationEvidence.UNRESOLVED,
                        source,
                        "wrapper_contract_sink_unresolved",
                        **common,
                    ))
                if not reconciliation.stored_procedure_mode:
                    return annotate(DbInvocation(
                        class_name,
                        method_name,
                        database,
                        None,
                        InvocationEvidence.UNRESOLVED,
                        source,
                        "wrapper_mode_unresolved",
                        **common,
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
                        **common,
                    ))

                rated = self._rate_literal_candidate(
                    class_name,
                    method_name,
                    database,
                    raw["command_text"],
                    source,
                    **common,
                )
                return annotate(rated)

            procedure_name = None
            procedure_schema = None
            if (
                reconciliation.stored_procedure_mode
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
                raw_command_text=raw.get("command_text") if procedure_name else None,
                **common,
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
                **common,
            ))
        if not reconciliation.stored_procedure_mode:
            return annotate(DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "wrapper_mode_unresolved",
                **common,
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
                **common,
            ))

        return annotate(self._rate_literal_candidate(
            class_name,
            method_name,
            database,
            raw["command_text"],
            source,
            **common,
        ))

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
