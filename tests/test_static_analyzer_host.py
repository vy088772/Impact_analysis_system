"""Ticket 01 behavior checks for the StaticAnalyzerHost and source snapshots."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.static_analyzer_host import (
    CONTRACT_VERSION,
    StaticAnalyzerHost,
    StaticAnalyzerHostError,
)
from config.settings import settings
from service import scan_store


HOST_PROJECT = PROJECT_ROOT / "tools" / "StaticAnalyzerHost" / "StaticAnalyzerHost.csproj"


def test_analyze_csharp_files_reports_completed_batches() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    with tempfile.TemporaryDirectory() as temp_dir:
        paths = [Path(temp_dir) / f"File{index}.cs" for index in range(3)]
        events: list[tuple[int, int, str]] = []

        def fake_batch(
            _host: StaticAnalyzerHost,
            batch: list[Path],
            source_roots: list[Path],
        ) -> list[dict]:
            return [{"source_id": str(path)} for path in batch]

        with (
            patch("code_analyzer.static_analyzer_host._MAX_HOST_COMMAND_CHARS", 100_000),
            patch("code_analyzer.static_analyzer_host._MAX_HOST_FILES_PER_BATCH", 2),
            patch.object(StaticAnalyzerHost, "_analyze_csharp_batch", new=fake_batch),
        ):
            results = host.analyze_csharp_files(
                paths,
                progress_callback=lambda current, total, item: events.append(
                    (current, total, item)
                ),
            )

    assert len(results) == 3
    assert [(current, total) for current, total, _ in events] == [(2, 3), (3, 3)]


def test_static_analyzer_host_contract() -> None:
    """The single host exposes versioned C# and SQL commands through JSON."""
    assert HOST_PROJECT.exists(), "StaticAnalyzerHost project must be included in source control"

    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    assert host.project_path == HOST_PROJECT
    version = host.ensure_ready()
    assert version["contract_version"] == CONTRACT_VERSION
    assert set(version["commands"]) == {"csharp", "sql", "decompile-wrapper", "semantic-binding"}

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "Example.cs"
        source_path.write_text(
            "public class Example { public void Save() { return; } }",
            encoding="utf-8",
        )
        csharp = host.analyze_csharp(source_path)
        assert csharp["contract_version"] == CONTRACT_VERSION
        assert csharp["methods"] == [
            {
                "class_name": "Example",
                "method_name": "Save",
                "start_offset": 23,
                "end_offset": 53,
            }
        ]

        sql = host.analyze_sql(source_path)
        assert sql["contract_version"] == CONTRACT_VERSION
        assert sql["operations"] == []


def test_the_analyzer_build_reports_the_contract_version_of_the_host() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    assert host.ensure_ready()["contract_version"] == CONTRACT_VERSION


def test_the_sql_command_answers_many_inputs_with_one_source_for_each_in_input_order(tmp_path: Path) -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    paths = []
    for name in ("First", "Second"):
        path = tmp_path / f"{name}.sql"
        path.write_text(f"CREATE PROCEDURE dbo.usp_{name} AS DELETE FROM dbo.T{name};", encoding="utf-8")
        paths.append(path)

    results = host.analyze_sql_files(paths)

    assert [result["operations"][0]["module"]["name"] for result in results] == ["usp_First", "usp_Second"]
    single = host.analyze_sql(paths[0])
    assert set(single) == {"contract_version", "operations", "parse_errors"}


def test_analyze_sql_files_splits_by_the_batch_limit_and_reports_each_batch(tmp_path: Path) -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    paths = [tmp_path / f"M{index}.sql" for index in range(5)]
    runs: list[list[Path]] = []
    events: list[tuple[int, int, str]] = []

    def fake_run(_host: StaticAnalyzerHost, *args: str) -> dict:
        batch = [Path(value) for value in args[1::2]]
        runs.append(batch)
        if len(batch) == 1:
            return {"operations": [], "parse_errors": []}
        return {"sources": [{"operations": [], "parse_errors": []} for _ in batch]}

    with (
        patch("code_analyzer.static_analyzer_host._MAX_HOST_FILES_PER_BATCH", 2),
        patch.object(StaticAnalyzerHost, "_run", new=fake_run),
    ):
        results = host.analyze_sql_files(paths, lambda *event: events.append(event))

    assert len(results) == 5
    assert [len(run) for run in runs] == [2, 2, 1]
    assert events == [(2, 5, str(paths[1])), (4, 5, str(paths[3])), (5, 5, str(paths[4]))]


def test_analyze_sql_files_splits_before_a_command_passes_the_character_limit(tmp_path: Path) -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    paths = [tmp_path / f"M{index}.sql" for index in range(4)]
    per_input = len(str(paths[0])) + len(" --input ")
    runs: list[int] = []

    def fake_run(_host: StaticAnalyzerHost, *args: str) -> dict:
        count = len(args) // 2
        runs.append(count)
        if count == 1:
            return {"operations": [], "parse_errors": []}
        return {"sources": [{"operations": [], "parse_errors": []} for _ in range(count)]}

    # Room for two inputs after the command name, not three.
    with (
        patch("code_analyzer.static_analyzer_host._MAX_HOST_COMMAND_CHARS", len("sql") + 2 * per_input + 1),
        patch.object(StaticAnalyzerHost, "_run", new=fake_run),
    ):
        results = host.analyze_sql_files(paths)

    assert len(results) == 4
    assert runs == [2, 2]


def test_one_sql_input_longer_than_the_character_limit_still_runs_alone(tmp_path: Path) -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    paths = [tmp_path / "A.sql", tmp_path / "B.sql"]
    runs: list[int] = []

    def fake_run(_host: StaticAnalyzerHost, *args: str) -> dict:
        runs.append(len(args) // 2)
        return {"operations": [], "parse_errors": []}

    with (
        patch("code_analyzer.static_analyzer_host._MAX_HOST_COMMAND_CHARS", 10),
        patch.object(StaticAnalyzerHost, "_run", new=fake_run),
    ):
        results = host.analyze_sql_files(paths)

    assert len(results) == 2
    assert runs == [1, 1]


def test_a_failed_sql_input_stops_the_run_with_its_path_in_the_error(tmp_path: Path) -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    good = tmp_path / "Good.sql"
    good.write_text("CREATE PROCEDURE dbo.usp_Good AS SELECT 1;", encoding="utf-8")
    missing = tmp_path / "Missing.sql"

    with pytest.raises(StaticAnalyzerHostError, match="Missing.sql"):
        host.analyze_sql_files([good, missing])


def test_a_sql_batch_response_with_a_wrong_entry_count_is_rejected(tmp_path: Path) -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    paths = [tmp_path / "A.sql", tmp_path / "B.sql"]

    with patch.object(
        StaticAnalyzerHost,
        "_run",
        return_value={"contract_version": CONTRACT_VERSION, "sources": [{"operations": [], "parse_errors": []}]},
    ):
        with pytest.raises(StaticAnalyzerHostError, match="invalid SQL batch response"):
            host.analyze_sql_files(paths)


def test_a_command_response_from_another_contract_version_is_rejected(tmp_path: Path) -> None:
    """The client rejects any command response whose contract version is not its own."""
    host = StaticAnalyzerHost(tmp_path / "StaticAnalyzerHost.csproj")
    host.dll_path.parent.mkdir(parents=True)
    host.dll_path.touch()
    response = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({"contract_version": CONTRACT_VERSION + 1, "operations": []}),
        stderr="",
    )

    with patch("code_analyzer.static_analyzer_host.subprocess.run", return_value=response):
        with pytest.raises(StaticAnalyzerHostError, match="contract mismatch"):
            host.analyze_sql(tmp_path / "Example.sql")


def test_a_version_report_from_another_contract_version_is_rejected() -> None:
    """The version check rejects a host that reports another contract version."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)

    with patch.object(
        StaticAnalyzerHost, "_run", return_value={"contract_version": CONTRACT_VERSION + 1}
    ):
        with pytest.raises(StaticAnalyzerHostError, match="contract mismatch"):
            host.version()


def _reference(server: str = "", database: str = "", schema: str = "", name: str = "") -> dict:
    return {"server": server, "database": database, "schema": schema, "name": name}


def _analyze_sql_text(sql: str) -> dict:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "module.sql"
        source_path.write_text(sql, encoding="utf-8")
        return host.analyze_sql(source_path)


def test_each_reference_keeps_every_name_part_it_states() -> None:
    """A read, write, call, or function reference carries four parts, and an unstated part is empty.

    The host used to keep the last two identifiers, so `PUR..Users` read `PUR`
    as a schema, and a one-part name read as `dbo`.
    """
    result = _analyze_sql_text(
        """CREATE PROCEDURE dbo.usp_Parts
AS
BEGIN
    SELECT Id FROM srv.PUR.dbo.Users;
    SELECT Id FROM [srv].[PUR].[dbo].[Users];
    SELECT Id FROM PUR.dbo.Users;
    SELECT Id FROM [PUR].[dbo].[Users];
    SELECT Id FROM COMMON.AVM;
    SELECT Id FROM [COMMON].[AVM];
    SELECT Id FROM AVM;
    SELECT Id FROM [AVM];
    SELECT Id FROM PUR..Users;
    SELECT Id FROM [PUR]..[Users];
    INSERT INTO PUR.dbo.Archive (Id) VALUES (1);
    EXEC PUR.COMMON.usp_Load;
    EXEC usp_Load;
    SELECT dbo.fn_Rate(Id), PUR.COMMON.fn_Rate(Id), [COMMON].[fn_Rate](Id) FROM Rates;
END;
"""
    )

    operations = result["operations"]
    four_part = _reference("srv", "PUR", "dbo", "Users")
    three_part = _reference("", "PUR", "dbo", "Users")
    two_part = _reference("", "", "COMMON", "AVM")
    one_part = _reference("", "", "", "AVM")
    database_no_schema = _reference("", "PUR", "", "Users")
    assert [operation["read_tables"] for operation in operations[:10]] == [
        [four_part],
        [four_part],
        [three_part],
        [three_part],
        [two_part],
        [two_part],
        [one_part],
        [one_part],
        [database_no_schema],
        [database_no_schema],
    ]
    assert operations[10]["write_tables"] == [_reference("", "PUR", "dbo", "Archive")]
    assert operations[11]["call_targets"] == [_reference("", "PUR", "COMMON", "usp_Load")]
    assert operations[12]["call_targets"] == [_reference("", "", "", "usp_Load")]
    assert operations[13]["function_references"] == [
        _reference("", "", "dbo", "fn_Rate"),
        _reference("", "PUR", "COMMON", "fn_Rate"),
        _reference("", "", "COMMON", "fn_Rate"),
    ]
    assert operations[13]["read_tables"] == [_reference("", "", "", "Rates")]


def test_duplicate_and_read_minus_write_removal_compare_all_four_parts() -> None:
    """A reference that states a database does not equal one that states none.

    The host reads syntax only, so it cannot know that the two name one table.
    It reports both, which ADR-0012 prefers to a lost read.
    """
    result = _analyze_sql_text(
        """CREATE PROCEDURE dbo.usp_Twice
AS
BEGIN
    SELECT u.Id FROM dbo.Users u JOIN PUR.dbo.Users p ON p.Id = u.Id JOIN [dbo].[users] x ON x.Id = u.Id;
    UPDATE dbo.Users SET Name = p.Name FROM dbo.Users u JOIN PUR.dbo.Users p ON p.Id = u.Id;
END;
"""
    )

    select, update = result["operations"]
    assert select["read_tables"] == [
        _reference("", "", "dbo", "Users"),
        _reference("", "PUR", "dbo", "Users"),
    ]
    assert update["write_tables"] == [_reference("", "", "dbo", "Users")]
    assert update["read_tables"] == [_reference("", "PUR", "dbo", "Users")]


def test_a_common_table_expression_keeps_a_schema_qualified_read_of_the_same_bare_name() -> None:
    """T-SQL cannot qualify a CTE name, so `dbo.X` names a real table and stays a read."""
    result = _analyze_sql_text(
        """CREATE PROCEDURE dbo.usp_Cte
AS
WITH X AS (SELECT Id FROM dbo.Source), Y AS (SELECT Id FROM dbo.X)
SELECT Id FROM Y;
"""
    )

    (select,) = result["operations"]
    assert select["read_tables"] == [
        _reference("", "", "dbo", "Source"),
        _reference("", "", "dbo", "X"),
    ]


@pytest.mark.parametrize(
    ("statement", "reads", "writes"),
    [
        ("WITH C AS (SELECT Id FROM dbo.Src) SELECT Id FROM C;", ["Src"], []),
        ("WITH C AS (SELECT Id FROM dbo.Src) SELECT Id INTO #t FROM C;", ["Src"], ["#t"]),
        (
            "WITH C AS (SELECT Id FROM dbo.Src) INSERT INTO dbo.Dest (Id) SELECT Id FROM C;",
            ["Src"],
            ["Dest"],
        ),
        (
            "WITH C AS (SELECT Id FROM dbo.Src) UPDATE dbo.Dest SET Id = C.Id FROM dbo.Dest d JOIN C ON C.Id = d.Id;",
            ["Src"],
            ["Dest"],
        ),
        (
            "WITH C AS (SELECT Id FROM dbo.Src) DELETE FROM dbo.Dest FROM dbo.Dest d JOIN C ON C.Id = d.Id;",
            ["Src"],
            ["Dest"],
        ),
    ],
)
def test_a_cte_read_in_the_main_part_is_no_table_read_for_each_statement_kind(
    statement: str, reads: list[str], writes: list[str]
) -> None:
    result = _analyze_sql_text(f"CREATE PROCEDURE dbo.usp_Cte AS\n{statement}\n")

    (operation,) = result["operations"]
    assert [ref["name"] for ref in operation["read_tables"]] == reads
    assert [ref["name"] for ref in operation["write_tables"]] == writes


def test_a_recursive_cte_and_chained_ctes_give_no_cte_read() -> None:
    result = _analyze_sql_text(
        """CREATE PROCEDURE dbo.usp_Cte
AS
WITH Tree AS (
    SELECT Id, ParentId FROM dbo.Node WHERE ParentId IS NULL
    UNION ALL
    SELECT n.Id, n.ParentId FROM dbo.Node n JOIN Tree t ON n.ParentId = t.Id
), Flat AS (SELECT Id FROM Tree)
SELECT Id FROM Flat;
"""
    )

    (select,) = result["operations"]
    assert select["read_tables"] == [_reference("", "", "dbo", "Node")]


def test_a_cte_name_wins_over_a_real_table_of_the_same_name_in_its_statement() -> None:
    result = _analyze_sql_text(
        """CREATE PROCEDURE dbo.usp_Cte
AS
WITH Users AS (SELECT Id FROM dbo.Users) SELECT Id FROM Users;
"""
    )

    (select,) = result["operations"]
    assert select["read_tables"] == [_reference("", "", "dbo", "Users")]


def test_the_ae_budget_log_summary_statement_reads_no_table1() -> None:
    """`EOR.AEBudgetLog_Summary_Qry` reads the CTE `Table1`, never a table of that name."""
    result = _analyze_sql_text(
        """CREATE PROCEDURE EOR.AEBudgetLog_Summary_Qry
AS
WITH Table1 AS (SELECT BudgetId FROM EOR.AEBudgetLog)
SELECT BudgetId INTO #table FROM Table1;
"""
    )

    (operation,) = result["operations"]
    assert operation["read_tables"] == [_reference("", "", "EOR", "AEBudgetLog")]
    assert operation["write_tables"] == [_reference("", "", "", "#table")]


def test_the_module_identity_states_no_database_and_an_unrecognised_module_states_no_schema() -> None:
    """The analysed module keeps type, schema, and name; the host never writes `dbo` for it."""
    named = _analyze_sql_text("CREATE PROCEDURE [COMMON].[usp_Load] AS SELECT Id FROM T;")
    unnamed = _analyze_sql_text("SELECT Id FROM T;")

    assert named["operations"][0]["module"] == {
        "type": "stored_procedure",
        "schema": "COMMON",
        "name": "usp_Load",
    }
    assert unnamed["operations"][0]["module"] == {
        "type": "unknown",
        "schema": "",
        "name": "module",
    }


def test_get_or_scan_persists_latest_csharp_source_snapshot() -> None:
    """A scan stores one complete C# snapshot keyed by its project-relative path."""
    previous_cache_root = settings.SCAN_CACHE_ROOT
    with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as cache_dir:
        root = Path(project_dir)
        source_path = root / "Example.cs"
        source_text = "// 😀\npublic class Example { public void Save() { return; } }"
        source_path.write_text(source_text, encoding="utf-8")
        stored_text = source_path.read_bytes().decode("utf-8-sig")
        other_path = root / "Other.cs"
        other_path.write_text("public class Other { public void Run() { return; } }", encoding="utf-8")
        utf16_path = root / "Utf16.cs"
        utf16_source = "// 😀\npublic class Utf16 { public void Read() { return; } }"
        utf16_path.write_bytes(utf16_source.encode("utf-16"))

        settings.SCAN_CACHE_ROOT = cache_dir
        try:
            scan_store.clear_cache(root)
            result = scan_store.get_or_scan(root, refresh=True)
            snapshot = result.source_snapshots["Example.cs"]
            assert snapshot.content == stored_text
            assert len(snapshot.content_hash) == 64
            assert [(span.class_name, span.method_name) for span in snapshot.method_spans] == [("Example", "Save")]
            assert snapshot.source_for(snapshot.method_spans[0]) == "public void Save() { return; }"
            assert [(span.class_name, span.method_name) for span in result.source_snapshots["Other.cs"].method_spans] == [("Other", "Run")]
            utf16_snapshot = result.source_snapshots["Utf16.cs"]
            assert utf16_snapshot.content == utf16_source
            assert utf16_snapshot.source_for(utf16_snapshot.method_spans[0]) == "public void Read() { return; }"

            cached = scan_store.get_or_scan(root, refresh=False)
            assert cached.source_snapshots["Example.cs"].content == stored_text
            assert "Other.cs" in cached.source_snapshots
            assert cached.source_snapshots["Utf16.cs"].content == utf16_source
        finally:
            scan_store.clear_cache(root)
            settings.SCAN_CACHE_ROOT = previous_cache_root
            shutil.rmtree(cache_dir, ignore_errors=True)


def _write_corpus(root: Path, file_count: int) -> list[Path]:
    """Write one old-style C# project that exercises the whole Command Source resolver.

    File0 declares a wrapper type whose method builds and runs a `SqlCommand`. Every other file
    both builds its own `SqlCommand` and calls that wrapper, so the analyzer has a wrapper
    definition to resolve in every file and a wrapper call site in every file. That shape is what
    drives the whole Command Source resolver: a corpus walk that runs per input file, per
    candidate method, or per call site shows up as time here rather than being skipped as
    "nothing in this project to resolve".
    """
    paths = []
    (root / "File0.cs").write_text(
        "using System;\n"
        "using System.Data;\n"
        "using System.Data.SqlClient;\n"
        "namespace Corpus {\n"
        "    public class SqlHelper {\n"
        "        public SqlConnection Connection;\n"
        "        public SqlHelper(SqlConnection connection) { Connection = connection; }\n"
        "        public void ExeProc(string procedureName) {\n"
        "            SqlCommand command = new SqlCommand(procedureName, Connection);\n"
        "            command.CommandType = CommandType.StoredProcedure;\n"
        "            command.ExecuteNonQuery();\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    paths.append(root / "File0.cs")
    for index in range(1, file_count):
        path = root / f"File{index}.cs"
        path.write_text(
            "using System;\n"
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "namespace Corpus {\n"
            f"    public class Caller{index} {{\n"
            f"        public void Direct{index}() {{\n"
            '            SqlConnection connection = new SqlConnection("Server=s;Database=d;");\n'
            f'            SqlCommand command = new SqlCommand("sp_direct_{index}", connection);\n'
            "            command.CommandType = CommandType.StoredProcedure;\n"
            "            command.ExecuteNonQuery();\n"
            "        }\n"
            f"        public void Wrapped{index}() {{\n"
            '            SqlConnection connection = new SqlConnection("Server=s;Database=d;");\n'
            "            SqlHelper helper = new SqlHelper(connection);\n"
            f'            helper.ExeProc("sp_wrapped_{index}");\n'
            "        }\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        paths.append(path)
    compile_items = "\n".join(
        f'    <Compile Include="File{index}.cs" />' for index in range(file_count)
    )
    (root / "Corpus.csproj").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Project ToolsVersion="4.0" DefaultTargets="Build" '
        'xmlns="http://schemas.microsoft.com/developer/msbuild/2003">\n'
        "  <ItemGroup>\n"
        '    <Reference Include="System" />\n'
        '    <Reference Include="System.Data" />\n'
        "  </ItemGroup>\n"
        "  <ItemGroup>\n"
        f"{compile_items}\n"
        "  </ItemGroup>\n"
        "</Project>\n",
        encoding="utf-8",
    )
    return paths


def test_one_batch_walks_the_corpus_once_not_once_per_input() -> None:
    """A batch of ten input files must not cost ten whole-corpus walks.

    The host parses every `.cs` file under `--source-root` as analysis context, then derives
    corpus-wide facts from it: the known type identities, the wrapper definitions, the used
    wrapper method identities, and the class declarations that carry a given type identity. All
    of them are pure functions of that context, but they were recomputed for each `--input` file
    and, in the resolver, for each call site, so one scan cost O(inputs x corpus). On the
    541-file Y-Docs TTPUR project one ten-file batch ran for over three and a half minutes, and
    no batch size could help, because every batch repeated the same walks.

    Assert the shape of the cost, not a wall-clock threshold: ten inputs must cost about what
    one input costs. The ratio holds on any machine; a second count would not.
    """
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        paths = _write_corpus(root, 200)

        start = time.perf_counter()
        single = host.analyze_csharp_files(paths[1:2], source_roots=[root])
        one_input_seconds = time.perf_counter() - start

        start = time.perf_counter()
        batch = host.analyze_csharp_files(paths[1:11], source_roots=[root])
        ten_input_seconds = time.perf_counter() - start

    assert len(single) == 1
    assert len(batch) == 10
    assert all(result["db_invocations"] for result in batch), (
        "the corpus memo and the class-declaration index must not drop invocations"
    )
    assert ten_input_seconds < one_input_seconds * 3, (
        f"ten inputs cost {ten_input_seconds:.2f}s against {one_input_seconds:.2f}s for one "
        "input: the corpus walk is running per input file again"
    )


def test_command_source_resolution_stays_linear_in_corpus_size() -> None:
    """Resolving one file must cost time proportional to the corpus, not to its square.

    Command Source resolution answers "which class declarations carry this type identity?" once
    per candidate method and once per call site. Answering it by walking every syntax tree made
    the cost O(sites x corpus), so a project that doubled in size got four times slower. That
    term is what kept one ten-file batch of the 541-file Y-Docs TTPUR project running for over
    three and a half minutes even after the corpus facts were memoized.

    Quadruple the corpus and analyze one file. A linear cost grows about fourfold, less once the
    fixed process start is counted; the quadratic cost grew about ninefold on this corpus.
    """
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    seconds = []
    for file_count in (200, 800):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _write_corpus(root, file_count)
            start = time.perf_counter()
            results = host.analyze_csharp_files(paths[1:2], source_roots=[root])
            seconds.append(time.perf_counter() - start)
            assert len(results) == 1
            assert results[0]["db_invocations"], (
                "the class-declaration index must not drop invocations"
            )

    small_corpus_seconds, large_corpus_seconds = seconds
    assert large_corpus_seconds < small_corpus_seconds * 6, (
        f"a fourfold corpus cost {large_corpus_seconds:.2f}s against "
        f"{small_corpus_seconds:.2f}s: Command Source resolution is walking the whole corpus "
        "per call site again"
    )


if __name__ == "__main__":
    test_static_analyzer_host_contract()
    test_get_or_scan_persists_latest_csharp_source_snapshot()
    test_one_batch_walks_the_corpus_once_not_once_per_input()
    test_command_source_resolution_stays_linear_in_corpus_size()
    print("StaticAnalyzerHost tests passed")


def test_a_cte_name_matches_a_read_without_regard_to_case() -> None:
    result = _analyze_sql_text(
        """CREATE PROCEDURE dbo.usp_Cte
AS
WITH c AS (SELECT Id FROM dbo.Src) SELECT Id FROM C;
"""
    )

    (select,) = result["operations"]
    assert select["read_tables"] == [_reference("", "", "dbo", "Src")]


def test_a_cte_name_does_not_reach_the_next_statement_of_the_module() -> None:
    result = _analyze_sql_text(
        """CREATE PROCEDURE dbo.usp_Cte
AS
BEGIN
    WITH X AS (SELECT Id FROM dbo.Src) SELECT Id FROM X;
    SELECT Id FROM X;
END;
"""
    )

    first, second = result["operations"]
    assert first["read_tables"] == [_reference("", "", "dbo", "Src")]
    assert second["read_tables"] == [_reference("", "", "", "X")]


def _write_test_statement(statement: str) -> dict:
    result = _analyze_sql_text(f"CREATE PROCEDURE dbo.usp_Alias AS\n{statement}\n")
    (operation,) = result["operations"]
    return operation


def test_an_update_alias_of_a_real_table_writes_that_table_and_no_longer_reads_it() -> None:
    operation = _write_test_statement(
        "UPDATE u SET Name = p.Name FROM dbo.Users u JOIN PUR.dbo.Other p ON p.Id = u.Id;"
    )

    assert operation["write_tables"] == [_reference("", "", "dbo", "Users")]
    assert operation["read_tables"] == [_reference("", "PUR", "dbo", "Other")]
    assert operation["unresolved_write_targets"] == []


def test_a_delete_alias_of_a_real_table_writes_that_table_and_no_longer_reads_it() -> None:
    operation = _write_test_statement(
        "DELETE u FROM dbo.Users u JOIN dbo.Other p ON p.Id = u.Id;"
    )

    assert operation["write_tables"] == [_reference("", "", "dbo", "Users")]
    assert operation["read_tables"] == [_reference("", "", "dbo", "Other")]
    assert operation["unresolved_write_targets"] == []


def test_an_alias_matches_without_regard_to_case_and_keeps_the_parts_the_from_clause_writes() -> None:
    operation = _write_test_statement(
        "UPDATE B1 SET Amount = 0 FROM [PUR].[BSPL].[BudgetBalanceSheet] AS b1;"
    )

    assert operation["write_tables"] == [_reference("", "PUR", "BSPL", "BudgetBalanceSheet")]
    assert operation["read_tables"] == []


def test_an_alias_of_a_temp_table_writes_that_temp_table() -> None:
    operation = _write_test_statement("UPDATE t SET Id = 1 FROM #work t;")

    assert operation["write_tables"] == [_reference("", "", "", "#work")]
    assert operation["read_tables"] == []


def test_an_alias_of_a_table_variable_writes_nothing() -> None:
    operation = _write_test_statement("UPDATE v SET Id = 1 FROM @rows v;")

    assert operation["write_tables"] == []
    assert operation["read_tables"] == []
    assert operation["unresolved_write_targets"] == []


@pytest.mark.parametrize(
    ("statement", "expected_alias"),
    [
        ("UPDATE s SET Id = 1 FROM (SELECT Id FROM dbo.Src) s;", "s"),
        ("WITH C AS (SELECT Id FROM dbo.Src) UPDATE c SET Id = 1 FROM C c;", "c"),
        ("WITH C AS (SELECT Id FROM dbo.Src) DELETE c FROM C c;", "c"),
    ],
)
def test_an_alias_of_a_subquery_or_a_cte_records_an_unresolved_target_and_guesses_no_table(
    statement: str, expected_alias: str
) -> None:
    operation = _write_test_statement(statement)

    assert operation["write_tables"] == []
    assert [ref["name"] for ref in operation["read_tables"]] == ["Src"]
    assert operation["unresolved_write_targets"] == [expected_alias]


def test_a_target_that_is_no_alias_still_writes_its_own_name() -> None:
    operation = _write_test_statement(
        "UPDATE dbo.Users SET Name = 'x' FROM dbo.Users u JOIN dbo.Other o ON o.Id = u.Id;"
    )

    assert operation["write_tables"] == [_reference("", "", "dbo", "Users")]
    assert operation["read_tables"] == [_reference("", "", "dbo", "Other")]
    assert operation["unresolved_write_targets"] == []


def test_the_bs_process_statement_writes_bspl_budget_balance_sheet() -> None:
    """`BSPL.sp_BSprocess` updates `BSPL.BudgetBalanceSheet` through the alias `B1`."""
    result = _analyze_sql_text(
        """CREATE PROCEDURE BSPL.sp_BSprocess
AS
update B1
set B1.Amount = B2.Amount
from BSPL.BudgetBalanceSheet B1
join BSPL.BudgetBalanceSheet_Src B2 on B2.Id = B1.Id;
"""
    )

    (operation,) = result["operations"]
    assert operation["write_tables"] == [_reference("", "", "BSPL", "BudgetBalanceSheet")]
    assert operation["read_tables"] == [_reference("", "", "BSPL", "BudgetBalanceSheet_Src")]


def test_an_alias_inside_a_derived_table_does_not_answer_for_an_alias_of_the_from_clause() -> None:
    operation = _write_test_statement(
        "UPDATE t SET a = 1 FROM (SELECT a FROM dbo.Other t) d JOIN dbo.Real t ON t.a = d.a;"
    )

    assert operation["write_tables"] == [_reference("", "", "dbo", "Real")]
    assert operation["read_tables"] == [_reference("", "", "dbo", "Other")]
    assert operation["unresolved_write_targets"] == []


def test_a_target_that_only_a_derived_table_uses_as_an_alias_still_writes_its_own_name() -> None:
    operation = _write_test_statement("UPDATE t SET a = 1 FROM (SELECT a FROM dbo.Other t) d;")

    assert operation["write_tables"] == [_reference("", "", "", "t")]
    assert operation["read_tables"] == [_reference("", "", "dbo", "Other")]
    assert operation["unresolved_write_targets"] == []


def test_an_alias_inside_a_parenthesised_join_is_an_alias_of_the_from_clause() -> None:
    operation = _write_test_statement(
        "UPDATE t SET a = 1 FROM (dbo.Other o JOIN dbo.Real t ON t.a = o.a) JOIN dbo.Third x ON x.a = t.a;"
    )

    assert operation["write_tables"] == [_reference("", "", "dbo", "Real")]
    assert [ref["name"] for ref in operation["read_tables"]] == ["Other", "Third"]


def test_an_alias_inside_an_odbc_escape_join_is_an_alias_of_the_from_clause() -> None:
    operation = _write_test_statement(
        "UPDATE t SET a = 1 FROM { oj dbo.Other o LEFT OUTER JOIN dbo.Real t ON t.a = o.a };"
    )

    assert operation["write_tables"] == [_reference("", "", "dbo", "Real")]
    assert operation["read_tables"] == [_reference("", "", "dbo", "Other")]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE dbo.T SET a = 1 WHERE EXISTS (SELECT 1 FROM dbo.S s WHERE s.id = dbo.T.id);",
        "UPDATE dbo.T SET a = 1 WHERE id IN (SELECT id FROM dbo.S);",
        "UPDATE dbo.T SET a = (SELECT MAX(b) FROM dbo.S);",
        "UPDATE t SET a = 1 FROM dbo.T t WHERE EXISTS (SELECT 1 FROM dbo.S s WHERE s.id = t.id);",
        "DELETE FROM dbo.T WHERE EXISTS (SELECT 1 FROM dbo.S s WHERE s.id = dbo.T.id);",
        "DELETE FROM dbo.T WHERE id IN (SELECT id FROM dbo.S);",
        "DELETE t FROM dbo.T t WHERE EXISTS (SELECT 1 FROM dbo.S s WHERE s.id = t.id);",
    ],
)
def test_an_update_or_delete_reads_the_tables_of_its_subqueries(statement: str) -> None:
    operation = _write_test_statement(statement)

    assert operation["write_tables"] == [_reference("", "", "dbo", "T")]
    assert operation["read_tables"] == [_reference("", "", "dbo", "S")]


def test_a_cte_name_inside_an_update_subquery_is_no_table_read() -> None:
    operation = _write_test_statement(
        "WITH C AS (SELECT Id FROM dbo.Src) UPDATE dbo.T SET a = 1 WHERE id IN (SELECT Id FROM C);"
    )

    assert operation["read_tables"] == [_reference("", "", "dbo", "Src")]


def test_a_subquery_that_reads_the_written_table_gives_no_read_of_it() -> None:
    operation = _write_test_statement(
        "DELETE FROM dbo.T WHERE id IN (SELECT MAX(id) FROM dbo.T);"
    )

    assert operation["write_tables"] == [_reference("", "", "dbo", "T")]
    assert operation["read_tables"] == []
