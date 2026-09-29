"""Ticket 03 behavior checks for AST-backed SQL execution operations."""

from __future__ import annotations

import sys
import tempfile
import time
from types import SimpleNamespace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.static_analyzer_host import CONTRACT_VERSION, StaticAnalyzerHost
from code_analyzer import sql_analyzer
from code_analyzer.sql_analyzer import ObjectListing, SQLAnalyzer
from service import sql_cache_store
from service.sql_execution_graph import GRAPH_VERSION, build_sql_execution_graph
from tests.sql_cache_fixtures import (
    CacheRoot,
    analyzer_operation,
    assert_relationships_resolve_to_known_nodes,
    cache_payload,
    case_variant_table_write_data,
    case_variant_temp_table_write_data,
    execution_graph,
    stubbed_procedures,
    write_cache,
)


TEST_SERVER = "vmsystest07"


def _write_sql_cache_fixture(
    cache_root: Path,
    database: str,
    payload: dict,
    cache_version: int | None = None,
) -> None:
    write_cache(
        cache_root,
        sql_cache_store.CacheIdentity.of(TEST_SERVER, database),
        payload,
        cache_version,
    )


def test_dump_all_sql_objects_keeps_sp_helpers_on_sql_analyzer() -> None:
    """Progress reporting must not move later SQLAnalyzer methods out of the class."""
    class FakeCursor:
        def execute(self, *args: object) -> None:
            return None

        def fetchone(self) -> tuple[str, None, None]:
            return ("CREATE PROCEDURE dbo.usp_Repro AS SELECT 1", None, None)

        def fetchall(self) -> list[object]:
            return []

    analyzer = SQLAnalyzer.__new__(SQLAnalyzer)
    analyzer.db_config = SimpleNamespace(alias="TestDb")
    analyzer.cursor = FakeCursor()
    analyzer.list_objects = lambda: [ObjectListing("procedures", "dbo", "usp_Repro")]

    data = analyzer.dump_all_sql_objects()

    assert [procedure["name"] for procedure in data["procedures"]] == ["usp_Repro"]
    assert "dependencies" not in data
    assert "write_dependencies" not in data


def test_sql_cache_rejects_graphless_payload() -> None:
    with CacheRoot() as cache_root:
        _write_sql_cache_fixture(
            cache_root,
            "TestDb",
            cache_payload("TestDb"),
        )

        assert sql_cache_store.load_cached(sql_cache_store.CacheIdentity.of(TEST_SERVER, "TestDb")) is None


def test_sql_cache_rejects_database_mismatch_from_memory_and_disk() -> None:
    mismatched_payload = cache_payload(
        "OtherDb",
        graph=execution_graph("OtherDb"),
    )
    with CacheRoot() as cache_root:
        _write_sql_cache_fixture(cache_root, "TestDb", mismatched_payload)

        assert sql_cache_store.load_cached(sql_cache_store.CacheIdentity.of(TEST_SERVER, "TestDb")) is None

        sql_cache_store._mem_cache[
            sql_cache_store.CacheIdentity.of(TEST_SERVER, "TestDb")
        ] = mismatched_payload
        assert sql_cache_store.load_cached(sql_cache_store.CacheIdentity.of(TEST_SERVER, "TestDb")) is None


def test_sql_cache_rejects_stale_payload_version() -> None:
    with CacheRoot() as cache_root:
        _write_sql_cache_fixture(
            cache_root,
            "TestDb",
            cache_payload(
                "TestDb",
                graph=execution_graph("TestDb"),
            ),
            cache_version=sql_cache_store._SQL_CACHE_VERSION - 1,
        )

        assert sql_cache_store.load_cached(sql_cache_store.CacheIdentity.of(TEST_SERVER, "TestDb")) is None


def test_the_graph_reads_the_schema_each_object_carries() -> None:
    """One cache holds `COMMON` and `HR` objects; no cache-wide field decides their schema."""
    data = cache_payload(
        "TestDb",
        procedures=["COMMON.usp_Load", "HR.usp_Load"],
        tables=["HR.Staff"],
    )

    graph = build_sql_execution_graph(data)

    assert sorted(node["id"] for node in graph["nodes"]) == [
        "stored_procedure:COMMON.usp_Load",
        "stored_procedure:HR.usp_Load",
        "table:HR.Staff",
    ]


def test_the_graph_reads_an_object_with_no_schema_field_as_dbo() -> None:
    """A cache written before each object carried its own schema holds only `dbo` objects."""
    data = cache_payload("TestDb", procedures=["usp_Load"], tables=["Orders"])
    for entry in [*data["procedures"], *data["tables"]]:
        del entry["schema"]

    graph = build_sql_execution_graph(data)

    assert sorted(node["id"] for node in graph["nodes"]) == [
        "stored_procedure:dbo.usp_Load",
        "table:dbo.Orders",
    ]


def test_sql_cache_rejects_stale_graph_version() -> None:
    """A cache built under any earlier graph version must be rejected.

    GRAPH_VERSION rises whenever the graph payload shape changes -- most
    recently to 6, when each `#name` temp table became one node for each
    module that uses it (temp-table-scope, ticket 03), so a graph that shares
    one temp table node fails this check until it is rebuilt.
    """
    assert GRAPH_VERSION == 6

    with CacheRoot() as cache_root:
        _write_sql_cache_fixture(
            cache_root,
            "TestDb",
            cache_payload(
                "TestDb",
                graph=execution_graph("TestDb", graph_version=GRAPH_VERSION - 1),
            ),
        )

        assert sql_cache_store.load_cached(sql_cache_store.CacheIdentity.of(TEST_SERVER, "TestDb")) is None


def test_sql_host_emits_typed_operations_with_module_and_source_evidence() -> None:
    """A SQL module keeps ordered DML facts instead of returning an empty operation list."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    sql = """CREATE PROCEDURE [dbo].[usp_SaveOrder]
AS
BEGIN
    SELECT Id FROM dbo.SourceOrder WHERE Id = @Id;
    INSERT INTO dbo.OrderArchive (Id, OrderNo)
        SELECT Id, OrderNo FROM dbo.SourceOrder;
    IF @Mode = 1
        UPDATE dbo.SOrder SET OrderNo = @OrderNo WHERE Id = @Id;
    ELSE
        DELETE FROM dbo.SOrder WHERE Id = @Id;
    SELECT Id INTO dbo.OrderSnapshot FROM dbo.SOrder;
END;
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "usp_SaveOrder.sql"
        source_path.write_text(sql, encoding="utf-8")

        result = host.analyze_sql(source_path)

    assert result["contract_version"] == CONTRACT_VERSION
    operations = result["operations"]
    assert [operation["operation_type"] for operation in operations] == [
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "SELECT_INTO",
    ]

    for sequence, operation in enumerate(operations, start=1):
        assert operation["sequence"] == sequence
        assert operation["module"] == {
            "type": "stored_procedure",
            "schema": "dbo",
            "name": "usp_SaveOrder",
        }
        assert operation["source"]["start_line"] >= 1
        assert operation["source"]["start_column"] >= 1
        assert operation["source"]["length"] > 0

    insert = operations[1]
    assert insert["write_tables"] == [{"server": "", "database": "", "schema": "dbo", "name": "OrderArchive"}]
    assert insert["written_columns"] == ["Id", "OrderNo"]
    assert insert["read_tables"] == [{"server": "", "database": "", "schema": "dbo", "name": "SourceOrder"}]

    update = operations[2]
    assert update["write_tables"] == [{"server": "", "database": "", "schema": "dbo", "name": "SOrder"}]
    assert update["written_columns"] == ["OrderNo"]
    assert update["where"] == "Id = @Id"
    assert update["branch_path"] == ["IF @Mode = 1"]
    assert update["conditions"] == ["IF @Mode = 1", "Id = @Id"]

    delete = operations[3]
    assert delete["write_tables"] == [{"server": "", "database": "", "schema": "dbo", "name": "SOrder"}]
    assert delete["where"] == "Id = @Id"
    assert delete["branch_path"] == ["ELSE (NOT (@Mode = 1))"]

    select_into = operations[4]
    assert select_into["write_tables"] == [{"server": "", "database": "", "schema": "dbo", "name": "OrderSnapshot"}]
    assert select_into["read_tables"] == [{"server": "", "database": "", "schema": "dbo", "name": "SOrder"}]


def test_sql_refresh_builds_and_reloads_typed_execution_graph() -> None:
    """SQL refresh persists graph nodes and relationships alongside SQL definitions."""
    class FakeSqlAnalyzer:
        def __init__(
            self,
            alias: str,
            *,
            server: str,
            database_name: str,
            user_id: str = "",
            password: str = "",
        ) -> None:
            self.alias = alias

        def connect(self) -> bool:
            return True

        def disconnect(self) -> None:
            return None

        def dump_all_sql_objects(self, progress_callback=None) -> dict:
            return cache_payload(
                self.alias,
                procedures={
                    "usp_SaveOrder": {
                        "definition": (
                            "CREATE PROCEDURE dbo.usp_SaveOrder AS "
                            "UPDATE dbo.SOrder SET OrderNo = @OrderNo WHERE Id = @Id;"
                        ),
                        "parameters": [],
                    }
                },
                views={
                    "vOrder": {
                        "definition": "CREATE VIEW dbo.vOrder AS SELECT Id FROM dbo.SOrder;",
                    }
                },
                tables={"SOrder": {"columns": []}},
            )

    with CacheRoot():
        original_analyzer = sql_analyzer.SQLAnalyzer
        sql_analyzer.SQLAnalyzer = FakeSqlAnalyzer
        try:
            data = sql_cache_store.get_or_dump(
                sql_cache_store.CacheIdentity.of(TEST_SERVER, "TestDb"),
                connection_server=TEST_SERVER,
                refresh=True,
            )
            # ADR-0031：舊有 dependencies/write_dependencies 欄位名稱不能出現在
            # persisted payload 裡這件事，改由這條 shape 斷言把關（原本靠已刪除
            # 的 scrubber `_without_legacy_dependency_fields()` 擋下）；日後若有
            # payload producer 重新長出這兩個舊欄位名稱，這裡就會失敗。
            assert set(data.keys()) == {
                "database",
                "procedures",
                "views",
                "functions",
                "tables",
                "sql_execution_graph",
            }
            graph = data["sql_execution_graph"]
            assert_relationships_resolve_to_known_nodes(graph)
            nodes_by_id = {node["id"]: node for node in graph["nodes"]}
            relationships = graph["relationships"]

            procedure = nodes_by_id["stored_procedure:dbo.usp_SaveOrder"]
            operation = nodes_by_id["dml_operation:stored_procedure:dbo.usp_SaveOrder:1"]
            view = nodes_by_id["view:dbo.vOrder"]
            view_operation = nodes_by_id["dml_operation:view:dbo.vOrder:1"]
            assert procedure["type"] == "stored_procedure"
            assert operation["operation_type"] == "UPDATE"
            assert operation["written_columns"] == ["OrderNo"]
            assert view["type"] == "view"
            assert {relationship["type"] for relationship in relationships} == {
                "contains",
                "writes",
                "reads",
            }
            assert any(
                relationship["type"] == "writes"
                and relationship["source"] == operation["id"]
                and relationship["target"] == "table:dbo.SOrder"
                for relationship in relationships
            )
            assert any(
                relationship["type"] == "reads"
                and relationship["source"] == view_operation["id"]
                and relationship["target"] == "table:dbo.SOrder"
                for relationship in relationships
            )

            sql_cache_store._mem_cache.clear()
            reloaded = sql_cache_store.load_cached(sql_cache_store.CacheIdentity.of(TEST_SERVER, "TestDb"))
            assert reloaded is not None
            assert reloaded["sql_execution_graph"] == graph
            assert set(reloaded.keys()) == set(data.keys())
        finally:
            sql_analyzer.SQLAnalyzer = original_analyzer


def test_each_relationship_records_the_database_and_server_its_reference_stated() -> None:
    """A reads, writes, or calls relationship keeps the parts its reference stated; a node keeps none.

    A reference that states no schema reads as `dbo` at the call site. A
    function reference to another Database resolves to no local function node.
    """
    data = cache_payload(
        "Response",
        procedures={
            "dbo.usp_Load": {
                "definition": """CREATE PROCEDURE dbo.usp_Load
AS
BEGIN
    INSERT INTO PUR.dbo.Archive (Id)
        SELECT u.Id FROM LNK.PUR.dbo.Users u JOIN Users l ON l.Id = u.Id JOIN PUR..Orders o ON o.Id = u.Id;
    EXEC PUR.COMMON.usp_Child;
    SELECT dbo.fn_Rate(1), response.dbo.fn_Rate(2), PUR.dbo.fn_Rate(3) FROM dbo.Rates;
END;
""",
            },
            "COMMON.usp_Child": {},
        },
        functions={
            "dbo.fn_Rate": {
                "definition": "CREATE FUNCTION dbo.fn_Rate(@Id int) RETURNS int AS BEGIN RETURN @Id END",
            },
        },
    )

    graph = build_sql_execution_graph(data)

    assert_relationships_resolve_to_known_nodes(graph)
    stated = {
        (relationship["type"], relationship["target"], relationship.get("server"), relationship.get("database"))
        for relationship in graph["relationships"]
        if relationship["type"] in {"reads", "writes", "calls"}
    }
    assert stated == {
        ("writes", "table:dbo.Archive", None, "PUR"),
        ("reads", "table:dbo.Users", "LNK", "PUR"),
        ("reads", "table:dbo.Users", None, None),
        ("reads", "table:dbo.Orders", None, "PUR"),
        ("calls", "stored_procedure:COMMON.usp_Child", None, "PUR"),
        ("reads", "table:dbo.Rates", None, None),
    }
    # Two references that name one node from two Databases stay two relationships.
    relationship_ids = [
        relationship["id"]
        for relationship in graph["relationships"]
        if relationship["type"] in {"reads", "writes", "calls"}
    ]
    assert len(relationship_ids) == len(set(relationship_ids))
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert set(nodes["table:dbo.Users"]) == {"id", "type", "schema", "name"}
    uses = [
        relationship
        for relationship in graph["relationships"]
        if relationship["type"] == "uses"
    ]
    # dbo.fn_Rate() and response.dbo.fn_Rate() name the local function; PUR.dbo.fn_Rate() does not.
    assert [relationship["target"] for relationship in uses] == [
        "function:dbo.fn_Rate",
        "function:dbo.fn_Rate",
    ]


def test_a_read_through_a_temp_table_keeps_the_database_its_base_read_stated() -> None:
    """The lineage read to the base table records the database the base read stated."""
    data = cache_payload(
        "Response",
        procedures={
            "dbo.usp_Stage": {
                "definition": """CREATE PROCEDURE dbo.usp_Stage
AS
BEGIN
    SELECT Id INTO #Stage FROM PUR.dbo.Users;
    SELECT Id FROM #Stage;
END;
""",
            },
        },
    )

    graph = build_sql_execution_graph(data)

    lineage_reads = [
        relationship for relationship in graph["relationships"] if relationship.get("lineage")
    ]
    assert [(relationship["target"], relationship.get("database")) for relationship in lineage_reads] == [
        ("table:dbo.Users", "PUR"),
    ]


def _crlf_procedure_definition() -> str:
    """A stored-procedure definition long enough to expose offset drift, using \\r\\n line endings."""
    lines = ["CREATE PROCEDURE dbo.usp_PadDelete AS", "BEGIN"]
    for index in range(40):
        lines.append(f"    -- pad line {index}")
    lines.append("    DELETE FROM dbo.PadTarget;")
    lines.append("END;")
    return "\r\n".join(lines) + "\r\n"


def test_graph_offsets_stay_within_definition_length_for_crlf_source() -> None:
    """The newline-safe write path must not let ScriptDom offsets outrun the cached definition text."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    definition = _crlf_procedure_definition()
    data = cache_payload(
        "TestDb",
        procedures={"usp_PadDelete": {"definition": definition, "parameters": []}},
        tables={"PadTarget": {"columns": []}},
    )

    graph = build_sql_execution_graph(data, host=host, project_root=PROJECT_ROOT)
    assert_relationships_resolve_to_known_nodes(graph)

    operation_nodes = [node for node in graph["nodes"] if node["type"] == "dml_operation"]
    assert operation_nodes, "expected the DELETE statement to produce an operation node"
    for node in operation_nodes:
        source = node["source"]
        end_offset = source["start_offset"] + source["length"]
        assert end_offset <= len(definition)


def test_pre_fix_crlf_doubling_produces_out_of_bounds_offsets() -> None:
    """Reproduces the corruption the old write_text() call produced on a Windows host.

    Windows text-mode writes translate every '\\n' to '\\r\\n'. A definition that
    already used '\\r\\n' line endings became '\\r\\r\\n' on disk, so ScriptDom parsed
    a longer string than the one persisted to the JSON cache. This test recreates
    that inflated file directly (bypassing the fixed write path) and asserts the
    resulting offsets overrun the original definition's length, proving this is
    the bug the fix addresses rather than an assertion with no failing baseline.
    """
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    definition = _crlf_procedure_definition()
    corrupted = definition.replace("\r\n", "\r\r\n")
    assert len(corrupted) > len(definition)

    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = Path(temp_dir) / "usp_PadDelete.sql"
        input_path.write_text(corrupted, encoding="utf-8", newline="")
        result = host.analyze_sql(input_path)

    operations = result["operations"]
    assert operations, "expected the DELETE statement to produce an operation"
    overruns = [
        operation
        for operation in operations
        if operation["source"]["start_offset"] + operation["source"]["length"] > len(definition)
    ]
    assert overruns, "expected the \\r\\n doubling to push at least one offset past the definition length"


def test_referenced_node_id_resolves_despite_a_case_variant_first_reference() -> None:
    """Ticket 01: `_ensure_referenced_node()` must return an id that names a node.

    `dbo.VQM` is referenced first in upper case, then again in lower case.
    `_add_node()` keeps the first node under a case-insensitive key, so the
    second reference must resolve back to that same node -- not to a second,
    unadded id that names nothing.
    """
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    data = case_variant_table_write_data(database="TestDb")

    graph = build_sql_execution_graph(data, host=host, project_root=PROJECT_ROOT)
    assert_relationships_resolve_to_known_nodes(graph)

    table_nodes = [
        node
        for node in graph["nodes"]
        if node["type"] == "table" and node["name"].casefold() == "vqm"
    ]
    assert len(table_nodes) == 1, "one case-insensitive key must keep exactly one node"

    writes = [
        relationship
        for relationship in graph["relationships"]
        if relationship["type"] == "writes"
    ]
    assert len(writes) == 2
    assert {relationship["target"] for relationship in writes} == {table_nodes[0]["id"]}


def test_write_to_real_table_survives_a_case_variant_read_through_a_temp_table() -> None:
    """Ticket 01: a case-variant temp-table reference must not unresolve a real write.

    `#TempStage` is created in one case and read back in another, the same
    shape that made `#Order` and `#tmpPart` the two largest sources of
    dangling ids in the PUR cache. Before the repair, the INSERT's read of
    `#tempstage` resolved to an id `_add_node()` never added, which put it in
    `missing_targets` and downgraded the whole operation -- including its
    proven write to `dbo.RealTable` -- to `unresolved`.
    """
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    data = case_variant_temp_table_write_data(database="TestDb")

    graph = build_sql_execution_graph(data, host=host, project_root=PROJECT_ROOT)
    assert_relationships_resolve_to_known_nodes(graph)

    writes = [
        relationship
        for relationship in graph["relationships"]
        if relationship["type"] == "writes"
    ]
    assert any(relationship["target"] == "table:dbo.RealTable" for relationship in writes)


def _temp_chain_procedure(base_table: str) -> list[dict]:
    """One procedure that fills `#t1` from a base table, copies it to `#t4`, and reads `#t4`."""
    chain = [base_table, "#t1", "#t2", "#t3", "#t4"]
    operations = [
        analyzer_operation("INSERT", sequence=index, reads=[source], writes=[target])
        for index, (source, target) in enumerate(zip(chain, chain[1:]), start=1)
    ]
    operations.append(analyzer_operation("SELECT", sequence=len(chain), reads=["#t4"]))
    return operations


def _lineage_reads(graph: dict) -> list[tuple[str, str]]:
    return sorted(
        (relationship["source"], relationship["target"])
        for relationship in graph["relationships"]
        if relationship.get("lineage")
    )


def _lineage_targets(graph: dict, source_id: str) -> set[str]:
    return {target for source, target in _lineage_reads(graph) if source == source_id}


def _temp_procedure(base_table: str, temp_table: str = "#tmp") -> list[dict]:
    """One procedure that fills a temp table from a base table, then reads it."""
    return [
        analyzer_operation("INSERT", sequence=1, reads=[base_table], writes=[temp_table]),
        analyzer_operation("SELECT", sequence=2, reads=[temp_table]),
    ]


def test_the_temp_table_expansion_ends_when_many_procedures_share_a_chain() -> None:
    """Test case 1 (cost): forty procedures that each run `#t1` to `#t4` build in a few seconds.

    The old expansion enumerated every path and took more than a minute here.
    """
    data, host = stubbed_procedures(
        "PUR",
        {f"dbo.usp_Chain{index:02d}": _temp_chain_procedure(f"dbo.Base{index:02d}") for index in range(40)},
    )

    started = time.monotonic()
    graph = build_sql_execution_graph(data, host=host)
    elapsed = time.monotonic() - started

    assert elapsed < 5, f"the graph build took {elapsed:.1f} seconds"
    assert_relationships_resolve_to_known_nodes(graph)
    final_reads = {f"dml_operation:stored_procedure:dbo.usp_Chain{index:02d}:5" for index in range(40)}
    assert final_reads <= {source for source, _ in _lineage_reads(graph)}
    for index in range(40):
        final_read = f"dml_operation:stored_procedure:dbo.usp_Chain{index:02d}:5"
        assert _lineage_targets(graph, final_read) == {f"table:dbo.Base{index:02d}"}


def test_a_cycle_of_temp_table_writes_gives_one_stable_result() -> None:
    """Test case 7 (cycle): A calls B, B calls A, and both write and read `#tmp`."""
    data, host = stubbed_procedures(
        "PUR",
        {
            "dbo.usp_A": [
                analyzer_operation("INSERT", sequence=1, reads=["dbo.BaseA"], writes=["#tmp"]),
                analyzer_operation("INSERT", sequence=2, reads=["#tmp"], writes=["#tmp"]),
                analyzer_operation("CALL", sequence=3, calls=["dbo.usp_B"]),
                analyzer_operation("SELECT", sequence=4, reads=["#tmp"]),
            ],
            "dbo.usp_B": [
                analyzer_operation("INSERT", sequence=1, reads=["dbo.BaseB"], writes=["#tmp"]),
                analyzer_operation("CALL", sequence=2, calls=["dbo.usp_A"]),
                analyzer_operation("SELECT", sequence=3, reads=["#tmp"]),
            ],
        },
    )

    first = build_sql_execution_graph(data, host=host)
    second = build_sql_execution_graph(data, host=host)

    assert_relationships_resolve_to_known_nodes(first)
    assert first["relationships"] == second["relationships"]
    assert {target for _, target in _lineage_reads(first)} == {"table:dbo.BaseA", "table:dbo.BaseB"}


def test_the_lineage_stage_reports_after_the_graph_stage() -> None:
    """Test case 11 (progress): the `lineage` stage follows the last `graph` report."""
    data, host = stubbed_procedures("PUR", {"dbo.usp_Chain": _temp_chain_procedure("dbo.Base")})
    reports: list[tuple[str, int, int]] = []

    build_sql_execution_graph(
        data,
        host=host,
        progress_callback=lambda stage, current, total, item: reports.append((stage, current, total)),
    )

    stages = [stage for stage, _, _ in reports]
    assert "lineage" in stages
    last_graph = max(index for index, stage in enumerate(stages) if stage == "graph")
    first_lineage = stages.index("lineage")
    assert last_graph < first_lineage
    assert set(stages[first_lineage:]) == {"lineage"}
    _, current, total = reports[-1]
    assert current == total


def test_two_procedures_that_use_one_temp_table_name_stay_separate() -> None:
    """Test case 2 (isolation): each read of `#tmp` resolves only to its own procedure's base table."""
    data, host = stubbed_procedures(
        "PUR",
        {"dbo.usp_A": _temp_procedure("dbo.BaseA"), "dbo.usp_B": _temp_procedure("dbo.BaseB")},
    )

    graph = build_sql_execution_graph(data, host=host)

    assert_relationships_resolve_to_known_nodes(graph)
    assert _lineage_targets(graph, "dml_operation:stored_procedure:dbo.usp_A:2") == {"table:dbo.BaseA"}
    assert _lineage_targets(graph, "dml_operation:stored_procedure:dbo.usp_B:2") == {"table:dbo.BaseB"}


def test_a_global_temp_table_stays_one_node_for_the_database() -> None:
    """Test case 8 (global temp table): two procedures with no call between them share `##g`."""
    data, host = stubbed_procedures(
        "PUR",
        {
            "dbo.usp_A": _temp_procedure("dbo.BaseA", "##g"),
            "dbo.usp_B": _temp_procedure("dbo.BaseB", "##g"),
        },
    )

    graph = build_sql_execution_graph(data, host=host)

    assert_relationships_resolve_to_known_nodes(graph)
    global_nodes = [node for node in graph["nodes"] if node.get("name") == "##g"]
    assert len(global_nodes) == 1
    assert "scope_module_id" not in global_nodes[0]
    assert _lineage_targets(graph, "dml_operation:stored_procedure:dbo.usp_A:2") == {
        "table:dbo.BaseA",
        "table:dbo.BaseB",
    }


def test_a_scoped_temp_table_node_keeps_its_written_name_and_names_its_module() -> None:
    """Test case 10 (node shape): `name` stays as written, `scope_module_id` names the owner."""
    data, host = stubbed_procedures(
        "PUR",
        {
            "dbo.usp_A": [
                analyzer_operation("INSERT", sequence=1, reads=["dbo.BaseA"], writes=["#Tmp"]),
                analyzer_operation("SELECT", sequence=2, reads=["#tmp"]),
            ],
            "dbo.usp_B": _temp_procedure("dbo.BaseB"),
        },
    )

    graph = build_sql_execution_graph(data, host=host)

    assert_relationships_resolve_to_known_nodes(graph)
    temp_nodes = [node for node in graph["nodes"] if node.get("name", "").startswith("#")]
    assert {(node["name"], node["type"], node["scope_module_id"]) for node in temp_nodes} == {
        ("#Tmp", "table", "stored_procedure:dbo.usp_A"),
        ("#tmp", "table", "stored_procedure:dbo.usp_B"),
    }
    assert len({node["id"] for node in temp_nodes}) == 2
    assert all(node["id"].startswith("table:dbo.#") for node in temp_nodes)
    plain_nodes = [node for node in graph["nodes"] if node["type"] == "table" and node not in temp_nodes]
    assert all("scope_module_id" not in node for node in plain_nodes)


def test_the_object_location_index_keeps_the_temp_table_names() -> None:
    """The index holds each temp table name once, whatever number of nodes carry it."""
    data, host = stubbed_procedures(
        "PUR",
        {"dbo.usp_A": _temp_procedure("dbo.BaseA"), "dbo.usp_B": _temp_procedure("dbo.BaseB")},
    )
    graph = build_sql_execution_graph(data, host=host)

    index = sql_cache_store.build_object_location_index(
        sql_cache_store.CacheIdentity.of(TEST_SERVER, "PUR"), cache_payload("PUR", graph=graph)
    )

    assert {"#tmp", "basea", "baseb"} <= index.tables
    assert len([name for name in index.tables if name.startswith("#")]) == 1


def test_a_temp_table_filled_and_read_in_one_procedure_resolves_with_the_real_analyzer_host() -> None:
    """`SELECT ... INTO #name` then `SELECT ... FROM #name` in one procedure, end to end."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    data = cache_payload(
        "TestDb",
        procedures={
            "dbo.usp_Stage": {
                "definition": """CREATE PROCEDURE dbo.usp_Stage
AS
BEGIN
    SELECT Id INTO #stage FROM dbo.Users;
    SELECT Id FROM #stage;
END;
"""
            },
        },
    )

    graph = build_sql_execution_graph(data, host=host, project_root=PROJECT_ROOT)

    assert_relationships_resolve_to_known_nodes(graph)
    temp_nodes = [node for node in graph["nodes"] if node.get("name") == "#stage"]
    assert [node["scope_module_id"] for node in temp_nodes] == ["stored_procedure:dbo.usp_Stage"]
    assert [target for _, target in _lineage_reads(graph)] == ["table:dbo.Users"]


if __name__ == "__main__":
    test_sql_host_emits_typed_operations_with_module_and_source_evidence()
    print("SQL execution graph tests passed")
