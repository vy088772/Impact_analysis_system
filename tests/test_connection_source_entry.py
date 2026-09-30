"""Tests for the connection source entry module (Seam D).

A connection source entry is the value that the C# Scan Result holds for one
connection variable of one source file. It has two shapes: a Resolved
Connection Source (a mapping) and a Legacy Connection Label (a bare string).
Each test calls the module with plain values and checks the result.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.connection_source_entry import (
    database_of,
    has_resolved_shape,
    resolved_entry,
    server_of,
    with_database,
)


def test_database_and_server_are_read_from_a_resolved_connection_source():
    entry = {"database": " OrdersDb ", "server": " sql01 "}

    assert database_of(entry) == "OrdersDb"
    assert server_of(entry) == "sql01"


def test_a_legacy_connection_label_has_a_database_and_no_server():
    assert database_of(" Y-Docs_TTPUR ") == "Y-Docs_TTPUR"
    assert server_of("Y-Docs_TTPUR") is None


def test_an_entry_with_no_database_gives_empty_text():
    assert database_of({"database": None, "server": "sql01"}) == ""
    assert database_of({"server": "sql01"}) == ""
    assert database_of("") == ""
    assert database_of(None) == ""


def test_an_absent_or_blank_server_gives_no_value():
    assert server_of({"database": "OrdersDb", "server": None}) is None
    assert server_of({"database": "OrdersDb", "server": "  "}) is None
    assert server_of({"database": "OrdersDb"}) is None
    assert server_of(None) is None


def test_with_database_keeps_the_server_and_a_field_the_module_does_not_know():
    entry = {"database": "OrdersDb", "server": "sql01", "declared_in": "Web.config"}

    remapped = with_database(entry, "PurchaseDb")

    assert remapped == {
        "database": "PurchaseDb",
        "server": "sql01",
        "declared_in": "Web.config",
    }
    assert entry["database"] == "OrdersDb"


def test_with_database_gives_a_bare_string_for_a_legacy_connection_label():
    assert with_database("Y-Docs_TTPUR", "PurchaseDb") == "PurchaseDb"


def test_has_resolved_shape_is_true_for_a_mapping_and_false_for_a_bare_string():
    assert has_resolved_shape({"database": "OrdersDb", "server": "sql01"}) is True
    assert has_resolved_shape("OrdersDb") is False


def test_resolved_entry_gives_the_fields_the_project_scanner_writes():
    entry = resolved_entry("OrdersDb", "sql01")

    assert entry == {"database": "OrdersDb", "server": "sql01"}
    assert type(entry) is dict
    assert list(entry) == ["database", "server"]
    assert resolved_entry("OrdersDb", None) == {"database": "OrdersDb", "server": None}
