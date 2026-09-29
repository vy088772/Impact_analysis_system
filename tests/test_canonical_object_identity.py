"""Seam 4: the Canonical Object Identity module over strings.

Strings go in and strings come out. No graph is built and no cache is opened.
The `object_names` list is the cross-repository agreement: the mirror module in
`llamaindex-spec-rag` passes the same list.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import canonical_object_identity as coi
from canonical_object_identity import ObjectName

AGREEMENT_PATH = Path(__file__).resolve().parent / "cross_repository_agreement.json"
OBJECT_NAMES = json.loads(AGREEMENT_PATH.read_text(encoding="utf-8"))["object_names"]


@pytest.mark.parametrize("case", OBJECT_NAMES, ids=[case["input"] for case in OBJECT_NAMES])
def test_each_agreed_name_parses_and_keys_as_stated(case: dict) -> None:
    parsed = coi.parse(case["input"])

    assert (parsed.database, parsed.schema, parsed.name) == (
        case["database"],
        case["schema"],
        case["name"],
    )
    assert coi.bare_key(case["input"]) == case["bare_key"]
    assert coi.full_key(case["input"]) == case["full_key"]


def test_the_agreement_holds_both_procedure_name_cases() -> None:
    inputs = {case["input"] for case in OBJECT_NAMES}

    assert {"usp_Load", "[COMMON].[usp_Load]"} <= inputs


def test_a_parse_keeps_the_server_but_no_key_reads_it() -> None:
    parsed = coi.parse("srv.PUR.dbo.Users")

    assert parsed.server == "srv"
    assert coi.full_key(parsed) == "pur.dbo.users"
    assert coi.full_key(parsed).count(".") == 2
    assert coi.full_key(parsed) == coi.full_key(dataclasses.replace(parsed, server="other"))
    assert coi.bare_key(parsed) == coi.bare_key(dataclasses.replace(parsed, server="other"))


def test_a_name_that_states_no_part_leaves_that_part_empty() -> None:
    assert coi.parse("Orders") == ObjectName(server="", database="", schema="", name="Orders")


def test_the_key_functions_accept_a_parsed_value_or_a_written_name() -> None:
    parsed = coi.parse("[PUR].[dbo].[Orders]")

    assert coi.bare_key(parsed) == coi.bare_key("[PUR].[dbo].[Orders]")
    assert coi.full_key(parsed) == coi.full_key("[PUR].[dbo].[Orders]")
    assert coi.bare_name(parsed) == coi.bare_name("[PUR].[dbo].[Orders]")


def test_the_case_preserving_variant_keeps_the_written_case() -> None:
    assert coi.bare_name("[COMMON].[usp_Load]") == "usp_Load"
    assert coi.bare_name(" dbo . fn_GetRate ") == "fn_GetRate"


def test_the_schema_qualified_name_keeps_the_written_case_and_drops_an_empty_schema() -> None:
    assert coi.schema_qualified(ObjectName("srv", "PUR", "COMMON", "AVM")) == "COMMON.AVM"
    assert coi.schema_qualified(ObjectName("", "PUR", "", "AVM")) == "AVM"
    assert coi.schema_qualified(ObjectName("", "", "dbo", "")) == ""


def test_a_part_written_alone_keys_without_brackets_or_case() -> None:
    assert coi.part_key("[COMMON]") == "common"
    assert coi.part_key(" Straße ") == "strasse"
    assert coi.part_key(None) == ""


def test_a_part_written_alone_keeps_its_dots() -> None:
    assert coi.part_key("Y.Docs") == "y.docs"


@pytest.mark.parametrize(
    ("written", "schema_key", "name_key"),
    [
        ("usp_Load", "", "usp_load"),
        ("[COMMON].[usp_Load]", "common", "usp_load"),
    ],
)
def test_a_procedure_name_gives_the_gateway_its_schema_and_name(
    written: str, schema_key: str, name_key: str
) -> None:
    """The C# analysis gateway keys a procedure name this way, and `path_id` reads both keys."""
    assert coi.part_key(coi.parse(written).schema) == schema_key
    assert coi.bare_key(written) == name_key


@pytest.mark.parametrize("written", ["usp_SO_Delete", "dbo.usp_SO_Delete", "[dbo].[usp_SO_Delete]"])
def test_a_procedure_bare_key_drops_the_schema_and_the_brackets(written: str) -> None:
    assert coi.bare_key(written) == "usp_so_delete"


def test_the_value_is_frozen() -> None:
    parsed = coi.parse("dbo.Orders")

    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.schema = "sales"  # type: ignore[misc]


def test_an_empty_or_missing_name_gives_empty_keys() -> None:
    assert coi.parse("") == ObjectName(server="", database="", schema="", name="")
    assert coi.bare_key(None) == ""
    assert coi.full_key(None) == ".."


def test_the_module_imports_nothing_from_this_project() -> None:
    tree = ast.parse((PROJECT_ROOT / "canonical_object_identity.py").read_text(encoding="utf-8"))
    project_packages = {"service", "code_analyzer", "config", "tools", "tests"}

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "the module uses no relative import"
            imported.add((node.module or "").split(".")[0])

    assert imported.isdisjoint(project_packages), imported
