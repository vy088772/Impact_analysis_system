"""Ticket 01 behavior checks for the StaticAnalyzerHost and source snapshots."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.static_analyzer_host import StaticAnalyzerHost
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
    assert version["contract_version"] == 2
    assert set(version["commands"]) == {"csharp", "sql"}

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "Example.cs"
        source_path.write_text(
            "public class Example { public void Save() { return; } }",
            encoding="utf-8",
        )
        csharp = host.analyze_csharp(source_path)
        assert csharp["contract_version"] == 2
        assert csharp["methods"] == [
            {
                "class_name": "Example",
                "method_name": "Save",
                "start_offset": 23,
                "end_offset": 53,
            }
        ]

        sql = host.analyze_sql(source_path)
        assert sql["contract_version"] == 2
        assert sql["operations"] == []


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


if __name__ == "__main__":
    test_static_analyzer_host_contract()
    test_get_or_scan_persists_latest_csharp_source_snapshot()
    print("StaticAnalyzerHost tests passed")