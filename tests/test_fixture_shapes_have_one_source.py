"""Every hand-built SQL cache shape in a test comes from one fixture module.

`.scratch/canonical-object-identity/` ticket 02. A shape change in Step 2a then
breaks tests/sql_cache_fixtures.py alone, not every test that restated the
shape. The check reads every Python file under the test directory and holds
four rules:

1. A SQL cache payload key fails outside the fixture module.
2. A graph format version or a contract version reads its constant, or an
   expression over it. A bare number fails.
3. A bare number passes in a comparison whose other side names the constant.
4. An analyzer operation's object-reference key fails outside the fixture
   module, the graph builder's test, and the analyzer host's test. Those two
   tests state the operation shape as their subject.

A JSON file holds data and no test, so the check does not read one.
"""

from __future__ import annotations

import ast
from pathlib import Path

TEST_DIRECTORY = Path(__file__).resolve().parent
FIXTURE_MODULE = "sql_cache_fixtures.py"

PAYLOAD_KEYS = frozenset({"procedures", "views", "functions", "sql_execution_graph"})
# `tables` is also a key of many other dictionaries, so only a dictionary that
# also names its `database` counts as a payload.
PAYLOAD_TABLES_KEY = "tables"
VERSION_CONSTANTS = {"graph_version": "GRAPH_VERSION", "contract_version": "CONTRACT_VERSION"}
OPERATION_KEYS = frozenset({"read_tables", "write_tables", "call_targets", "function_references"})
OPERATION_SHAPE_TESTS = frozenset(
    {FIXTURE_MODULE, "test_sql_execution_graph.py", "test_static_analyzer_host.py"}
)


def _string_keys(node: ast.Dict) -> set[str]:
    return {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}


def _names_a_version_constant(node: ast.AST) -> bool:
    constants = set(VERSION_CONSTANTS.values())
    return any(
        (isinstance(child, ast.Name) and child.id in constants)
        or (isinstance(child, ast.Attribute) and child.attr in constants)
        for child in ast.walk(node)
    )


def _holds_a_bare_number(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Constant) and type(child.value) in (int, float)
        for child in ast.walk(node)
    )


def _reads_a_version(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
        and any(version in node.slice.value for version in VERSION_CONSTANTS)
    )


def _stored_keys(node: ast.AST) -> list[tuple[int, str]]:
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        targets = [node.target]
    stored = []
    for target in targets:
        for child in ast.walk(target):
            if (
                isinstance(child, ast.Subscript)
                and isinstance(child.slice, ast.Constant)
                and child.slice.value in PAYLOAD_KEYS | {PAYLOAD_TABLES_KEY}
            ):
                stored.append((child.lineno, child.slice.value))
    return stored


def violations(source: str, file_name: str) -> dict[str, list[int]]:
    """Return the line of every rule break in one test file, by rule."""
    found: dict[str, list[int]] = {"payload key": [], "version": [], "operation key": []}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            keys = _string_keys(node)
            if file_name != FIXTURE_MODULE and (
                keys & PAYLOAD_KEYS or {PAYLOAD_TABLES_KEY, "database"} <= keys
            ):
                found["payload key"].append(node.lineno)
            if file_name not in OPERATION_SHAPE_TESTS and keys & OPERATION_KEYS:
                found["operation key"].append(node.lineno)
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value in VERSION_CONSTANTS
                    and _holds_a_bare_number(value)
                    and not _names_a_version_constant(value)
                ):
                    found["version"].append(value.lineno)
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if (
                    keyword.arg in VERSION_CONSTANTS
                    and _holds_a_bare_number(keyword.value)
                    and not _names_a_version_constant(keyword.value)
                ):
                    found["version"].append(keyword.value.lineno)
        elif isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(_reads_a_version(operand) for operand in operands) and not any(
                _names_a_version_constant(operand) for operand in operands
            ) and any(_holds_a_bare_number(operand) for operand in operands):
                found["version"].append(node.lineno)
        if file_name != FIXTURE_MODULE:
            found["payload key"].extend(line for line, _ in _stored_keys(node))
    return {rule: sorted(lines) for rule, lines in found.items()}


def _test_files() -> list[Path]:
    own_file = Path(__file__).resolve()
    return sorted(path for path in TEST_DIRECTORY.glob("*.py") if path.resolve() != own_file)


def _breaks_of(rule: str) -> list[str]:
    breaks = []
    for path in _test_files():
        for line in violations(path.read_text(encoding="utf-8"), path.name)[rule]:
            breaks.append(f"{path.name}:{line}")
    return breaks


def test_rule_one_no_payload_key_sits_outside_the_fixture_module() -> None:
    assert _breaks_of("payload key") == [], "build the payload with tests.sql_cache_fixtures.cache_payload"


def test_rules_two_and_three_every_version_reads_its_constant() -> None:
    assert _breaks_of("version") == [], "read GRAPH_VERSION or CONTRACT_VERSION, not a bare number"


def test_rule_four_no_operation_key_sits_outside_the_fixture_module() -> None:
    assert _breaks_of("operation key") == [], "build the operation with tests.sql_cache_fixtures.analyzer_operation"


# ----------------------------------------------------------- each rule fires


def test_a_payload_literal_and_a_payload_store_break_rule_one() -> None:
    source = (
        'payload = {"database": "PUR", "procedures": []}\n'
        'listing = {"database": "PUR", "tables": []}\n'
        'result = {"tables": []}\n'
        'payload["sql_execution_graph"] = {}\n'
    )

    assert violations(source, "test_example.py")["payload key"] == [1, 2, 4]
    assert violations(source, FIXTURE_MODULE)["payload key"] == []


def test_a_bare_version_number_breaks_rule_two_unless_the_other_side_names_the_constant() -> None:
    source = (
        'graph = {"graph_version": 2}\n'
        'stale = {"graph_version": GRAPH_VERSION - 1}\n'
        "graph = execution_graph(\"PUR\", graph_version=3)\n"
        'assert response["contract_version"] == 2\n'
        'assert response["contract_version"] == CONTRACT_VERSION\n'
        "assert GRAPH_VERSION == 4\n"
    )

    assert violations(source, "test_example.py")["version"] == [1, 3, 4]


def test_an_operation_literal_breaks_rule_four_outside_the_two_contract_tests() -> None:
    source = 'operation = {"operation_type": "UPDATE", "write_tables": ["dbo.SOrder"]}\n'

    assert violations(source, "test_example.py")["operation key"] == [1]
    assert violations(source, "test_sql_execution_graph.py")["operation key"] == []
    assert violations(source, "test_static_analyzer_host.py")["operation key"] == []
