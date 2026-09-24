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


def test_a_common_table_expression_drops_a_schema_qualified_read_of_the_same_bare_name() -> None:
    """The exclusion compares the bare name only, so a CTE `X` also drops `dbo.X`.

    Out of Scope records this as a defect. A fix fails this case first, and the
    fixer then corrects Out of Scope.

    The exclusion reads only the CTE names inside the fragment it walks. The
    CTE bodies are one fragment, so `Y` reading `dbo.X` loses `dbo.X`. The main
    query is another fragment, so its read of the CTE `Y` stays as a table read.
    """
    result = _analyze_sql_text(
        """CREATE PROCEDURE dbo.usp_Cte
AS
WITH X AS (SELECT Id FROM dbo.Source), Y AS (SELECT Id FROM dbo.X)
SELECT Id FROM Y;
"""
    )

    (select,) = result["operations"]
    assert select["read_tables"] == [
        _reference("", "", "", "Y"),
        _reference("", "", "dbo", "Source"),
    ]


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