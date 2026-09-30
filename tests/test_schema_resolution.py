"""The schema source vocabulary: the values, the default of a record, and the order of strength."""

from __future__ import annotations

import json

import pytest

from schema_resolution import SchemaSource, recorded_source, strongest_source


def test_each_schema_source_is_the_text_a_relationship_records() -> None:
    assert [str(source) for source in SchemaSource] == [
        "written",
        "module_schema",
        "default_schema",
        "system",
        "unresolved",
    ]
    assert json.dumps({"schema_source": SchemaSource.MODULE_SCHEMA}) == '{"schema_source": "module_schema"}'


@pytest.mark.parametrize(
    ("recorded", "schema", "expected"),
    [
        ("module_schema", "COMMON", "module_schema"),
        ("unresolved", "", "unresolved"),
        ("", "dbo", "written"),
        (None, "dbo", "written"),
        ("", "", "unresolved"),
        (None, None, "unresolved"),
    ],
)
def test_a_record_with_no_schema_source_reads_as_written_with_a_schema_else_unresolved(
    recorded: str | None, schema: str | None, expected: str
) -> None:
    assert recorded_source(recorded, schema) == expected


def test_the_strongest_of_two_schema_sources_is_the_one_nearer_to_written() -> None:
    assert strongest_source("default_schema", "written") == "written"
    assert strongest_source("module_schema", "unresolved") == "module_schema"
    assert strongest_source("system", "system") == "system"


def test_a_schema_source_the_rule_does_not_know_is_the_weakest() -> None:
    assert strongest_source("other", "unresolved") == "unresolved"
    assert strongest_source("unresolved", "other") == "unresolved"
