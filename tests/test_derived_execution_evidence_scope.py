"""Ticket 03: the derivation is asked for an explicit scope, not a request.

`DerivedExecutionEvidenceScope` is the named identity Derived Execution
Evidence (CONTEXT.md, ADR-0013) is keyed on. These checks pin down its
equality contract directly, at the seam `DerivedExecutionEvidenceScope.of()`
-- independent of any scan/SQL-cache fixtures, since no derivation behaviour
is meant to change in this ticket.
"""

from __future__ import annotations

from pathlib import Path

from service import derived_execution_evidence_store
from service.derived_execution_evidence import DerivedExecutionEvidenceScope
from service.schemas import AnalyzeRequest, AzureSource
from service.sql_cache_store import CacheIdentity


def _request(**overrides) -> AnalyzeRequest:
    fields = {
        "source": AzureSource(project="Proj", repo="Repo", branch="main", path="Sub"),
        "program_names": ["SomeProgram"],
        "database": "ETON",
        "db_server": "vmsystest07",
        "db_name": "ETON",
        "wrapper_contract": "legacy_wrapper",
    }
    fields.update(overrides)
    return AnalyzeRequest(**fields)


_ROOTS = [Path("/data/repos/Proj/Repo/Sub")]
_ETON_ON_SEVEN = CacheIdentity.of("vmsystest07", "ETON")


def test_identical_inputs_produce_equal_scope() -> None:
    left = DerivedExecutionEvidenceScope.of(_request(), _ROOTS, _ETON_ON_SEVEN)
    right = DerivedExecutionEvidenceScope.of(_request(), _ROOTS, _ETON_ON_SEVEN)
    assert left == right
    assert hash(left) == hash(right)


def test_fields_outside_the_scope_do_not_change_it() -> None:
    baseline = DerivedExecutionEvidenceScope.of(_request(), _ROOTS, _ETON_ON_SEVEN)
    varied = DerivedExecutionEvidenceScope.of(
        _request(
            program_names=["OtherProgram"],
            question="which programs touch ETON.ManifestNew?",
            include_snippets=False,
            include_sp_defs=True,
            expand_depth=1,
            refresh=True,
            max_paths=5,
            system="some-system-id",
        ),
        _ROOTS,
        _ETON_ON_SEVEN,
    )
    assert varied == baseline


def test_server_naming_that_resolves_the_same_does_not_change_the_scope() -> None:
    """A named-instance suffix and case differences never reach the SQL cache
    key (see sql_cache_store.normalize_server) -- so they must not fork the
    scope identity either, or two requests routing to the same cache would
    derive twice."""
    baseline = DerivedExecutionEvidenceScope.of(_request(), _ROOTS, _ETON_ON_SEVEN)
    same_server = DerivedExecutionEvidenceScope.of(
        _request(db_server="VMSYSTEST07\\SQLEXPRESS"),
        _ROOTS,
        CacheIdentity.of("VMSYSTEST07\\SQLEXPRESS", "ETON"),
    )
    assert same_server == baseline


def test_non_string_wrapper_contract_selector_is_treated_as_absent() -> None:
    """`_rated_execution_invocations` only ever honours a string wrapper
    contract selector; a non-string value already falls back to "" today.
    The scope must fold the same way, or a request the derivation treats as
    contract-less would fork into its own scope for no reason."""
    baseline = DerivedExecutionEvidenceScope.of(_request(wrapper_contract=""), _ROOTS, _ETON_ON_SEVEN)
    non_string = DerivedExecutionEvidenceScope.of(
        _request(wrapper_contract=["a", "b"]), _ROOTS, _ETON_ON_SEVEN
    )
    assert non_string == baseline


def test_different_database_identity_changes_the_scope() -> None:
    baseline = DerivedExecutionEvidenceScope.of(_request(), _ROOTS, _ETON_ON_SEVEN)
    other_database = DerivedExecutionEvidenceScope.of(
        _request(database="PUR"), _ROOTS, CacheIdentity.of("vmsystest07", "PUR")
    )
    other_server = DerivedExecutionEvidenceScope.of(
        _request(db_server="othersystest01"), _ROOTS, CacheIdentity.of("othersystest01", "ETON")
    )
    other_db_name = DerivedExecutionEvidenceScope.of(_request(db_name="PUR"), _ROOTS, _ETON_ON_SEVEN)
    assert other_database != baseline
    assert other_server != baseline
    assert other_db_name != baseline


def test_one_database_name_on_two_hosts_gives_two_retention_keys() -> None:
    on_seven = DerivedExecutionEvidenceScope.of(
        _request(db_server=""), _ROOTS, CacheIdentity.of("vmsystest07", "ETON")
    )
    on_eight = DerivedExecutionEvidenceScope.of(
        _request(db_server=""), _ROOTS, CacheIdentity.of("vmsystest08", "ETON")
    )
    assert on_seven != on_eight
    assert derived_execution_evidence_store._key(on_seven) != derived_execution_evidence_store._key(on_eight)


def test_different_wrapper_contract_selector_changes_the_scope() -> None:
    baseline = DerivedExecutionEvidenceScope.of(_request(), _ROOTS, _ETON_ON_SEVEN)
    other_contract = DerivedExecutionEvidenceScope.of(
        _request(wrapper_contract="other_wrapper"), _ROOTS, _ETON_ON_SEVEN
    )
    assert other_contract != baseline


def test_different_repository_scan_roots_changes_the_scope() -> None:
    baseline = DerivedExecutionEvidenceScope.of(_request(), _ROOTS, _ETON_ON_SEVEN)
    other_roots = DerivedExecutionEvidenceScope.of(
        _request(), [Path("/data/repos/Proj/Repo/OtherSub")], _ETON_ON_SEVEN
    )
    assert other_roots != baseline


def test_scope_is_usable_as_a_dict_key() -> None:
    first = DerivedExecutionEvidenceScope.of(_request(), _ROOTS, _ETON_ON_SEVEN)
    second = DerivedExecutionEvidenceScope.of(_request(), _ROOTS, _ETON_ON_SEVEN)
    retained = {first: "derived once"}
    assert retained[second] == "derived once"
