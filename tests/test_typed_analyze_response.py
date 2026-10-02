import copy
import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from service.schemas import AnalyzeResponse
from tests.analyze_response_fixtures import actual_http_json


AGREEMENT_PATH = Path(__file__).parent / "cross_repository_agreement.json"


def agreement_samples() -> list[dict]:
    agreement = json.loads(
        AGREEMENT_PATH.read_text()
    )["analyze_response"]
    invocation = {**agreement["wrapper"], **agreement["invocation"]}
    path = {**agreement["wrapper"], **agreement["execution_path"]}
    program = {
        **agreement["program"],
        "database_invocations": [invocation, {**invocation, "shared_component": {"kind": "view_component", "name": "Menu"}}],
        "diagnostics": [{**invocation, "diagnostic": True}, {**invocation, "diagnostic": True, "shared_component": {"kind": "view_component", "name": "Menu"}}],
        "execution_paths": [path, {**path, "terminal_operation": None}],
        "compact_execution_paths": [agreement["compact_path"]],
    }
    samples = agreement["samples"] + [{"programs": [program], "not_found": [], "source_root": "fixture"}]
    for rating in agreement["invocation_ratings"]:
        sample = copy.deepcopy(samples[-1])
        sample["programs"][0]["database_invocations"][0]["evidence"] = rating
        samples.append(sample)
    for rating in agreement["wrapper_ratings"]:
        sample = copy.deepcopy(samples[-1])
        sample["programs"][0]["database_invocations"][0]["evidence_status"] = rating
        samples.append(sample)
    return samples


def test_a_missing_agreement_file_fails_instead_of_skipping(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(globals(), "AGREEMENT_PATH", tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        agreement_samples()


@pytest.mark.parametrize("change", ["missing", "renamed", "unknown"])
def test_every_structured_record_rejects_contract_changes(change: str) -> None:
    original = agreement_samples()[2]
    model = AnalyzeResponse.model_validate_json(json.dumps(original))
    pending: list[tuple[tuple[str | int, ...], BaseModel]] = [((), model)]
    while pending:
        record_path, record = pending.pop()
        unknown_checked = False
        for name, field in type(record).model_fields.items():
            if name not in record.model_fields_set:
                continue
            wire_name = field.alias or name
            value = getattr(record, name)
            if isinstance(value, BaseModel):
                pending.append(((*record_path, wire_name), value))
            elif isinstance(value, list):
                pending.extend(
                    ((*record_path, wire_name, index), item)
                    for index, item in enumerate(value) if isinstance(item, BaseModel)
                )
            if change != "unknown" and not field.is_required():
                continue
            if change == "unknown" and unknown_checked:
                continue
            sample = copy.deepcopy(original)
            target = sample
            for part in record_path:
                target = target[part]
            if change == "unknown":
                target["unknown_contract_field"] = "hidden"
            else:
                removed = target.pop(wire_name)
                if change == "renamed":
                    target[f"renamed_{wire_name}"] = removed
            with pytest.raises(ValidationError):
                AnalyzeResponse.model_validate_json(json.dumps(sample))
            if change == "unknown":
                unknown_checked = True


def represented_fields(models: Sequence[BaseModel]) -> dict[str, set[str]]:
    represented: dict[str, set[str]] = {}

    def visit(value):
        if isinstance(value, BaseModel):
            represented.setdefault(type(value).__name__, set()).update(
                field.alias or name
                for name, field in type(value).model_fields.items()
                if name in value.model_fields_set
            )
            for name in value.model_fields_set:
                visit(getattr(value, name))
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(models)
    return represented


def test_every_agreement_sample_round_trips_without_added_or_lost_fields() -> None:
    for sample in agreement_samples():
        model = AnalyzeResponse.model_validate_json(json.dumps(sample))
        assert json.loads(model.model_dump_json(by_alias=True)) == sample


def test_every_declared_structured_field_is_represented_in_the_agreement() -> None:
    models = [AnalyzeResponse.model_validate_json(json.dumps(sample)) for sample in agreement_samples()]
    represented = represented_fields(models)
    schema = AnalyzeResponse.model_json_schema(mode="validation")
    for name, record in {"AnalyzeResponse": schema, **schema.get("$defs", {})}.items():
        if "properties" in record:
            assert set(record["properties"]) == represented.get(name, set()), name


@pytest.mark.parametrize("field_path,value", [
    (("not_found",), None),
    (("programs", 0, "methods"), None),
    (("programs", 0, "methods", 0, "name"), 1),
    (("programs", 0, "methods", 0, "unknown"), "hidden"),
    (("programs", 0, "code_snippets", 0, "unknown"), "hidden"),
    (("programs", 0, "related_programs", 0, "depth"), True),
    (("programs", 0, "related_programs", 0, "depth"), "1"),
    (("programs", 0, "related_programs", 0, "snippet"), None),
    (("programs", 0, "database_invocations", 0, "evidence"), "verified"),
    (("programs", 0, "database_invocations", 0, "evidence_status"), "verified"),
    (("programs", 0, "database_invocations", 0, "method_arity"), True),
    (("programs", 0, "compact_execution_paths_meta", "omitted_paths"), "1"),
    (("programs", 0, "view_layer", 0, "fields", 0, "events", "UnknownEvent"), 1),
    (("programs", 0, "compact_execution_paths", 0, "relevance_key"), [True]),
    (("programs", 0, "execution_paths", 0, "source_span", "unknown"), "hidden"),
])
def test_invalid_fields_fail_through_the_json_parse_interface(field_path, value) -> None:
    sample = copy.deepcopy(agreement_samples()[2])
    target = sample
    for part in field_path[:-1]:
        target = target[part]
    target[field_path[-1]] = value
    with pytest.raises(ValidationError):
        AnalyzeResponse.model_validate_json(json.dumps(sample))


@pytest.mark.parametrize("payload", ["{", "null", "[]", '{"programs": []}'])
def test_malformed_or_incomplete_json_is_not_empty_evidence(payload: str) -> None:
    with pytest.raises(ValidationError):
        AnalyzeResponse.model_validate_json(payload)


def test_the_actual_http_response_satisfies_the_json_contract() -> None:
    response = AnalyzeResponse.model_validate_json(actual_http_json())
    assert response.not_found == ["Missing"]
    program = response.programs[0]
    assert program.program == "OrderPage"
    assert program.database_invocations[0].procedure_name == "usp_saveorder"
    assert program.execution_paths[0].target == "dbo.SOrder"
    assert program.compact_execution_paths[0].terminal_operation == "UPDATE"
    assert program.sp_definitions[0].parameters == ["@Id int"]
    assert program.code_snippets[0].text
    assert program.view_layer[0].file == "OrderPage.aspx"


def test_the_json_contract_rejects_unknown_envelope_fields() -> None:
    with pytest.raises(ValidationError):
        AnalyzeResponse.model_validate_json(
            '{"programs": [], "not_found": [], "source_root": "", "renamed": []}'
        )