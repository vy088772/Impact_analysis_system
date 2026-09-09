"""Ticket 04 (04-framework-label-reports-parsers-mount-by-union.md, ADR-0021):

The Framework Label reports which framework a scan root looks like; it no
longer decides which parsers mount. Parsers mount by the union of view file
extensions actually present under the scan root, so a mixed root loses
neither WebForms nor Razor evidence. A root whose framework cannot be
identified fails loudly instead of silently falling back to a C#-only scan.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.models import FrameworkType
from code_analyzer.project_scanner import ProjectScanner, ProjectScanResult
from code_analyzer.project_type_detector import ProjectTypeDetector


# ============================================================
# ProjectTypeDetector: the label is honest, and mounting is by union
# ============================================================


def test_plain_csharp_project_with_no_web_markers_reports_dotnet_framework_not_unknown(
    tmp_path,
) -> None:
    """A console/scheduler-shaped project (only .cs files, no web.config, no
    appsettings.json) is a real, identifiable .NET project -- not a detection
    failure. Y-Docs_TTPUR's `TaskSchedule` scan root is shaped exactly like
    this; it must keep scanning, not start raising on every refresh."""
    root = tmp_path / "TaskSchedule"
    root.mkdir()
    (root / "Program.cs").write_text("class Program {}", encoding="utf-8")

    detector = ProjectTypeDetector(str(root))
    framework = detector.detect()

    assert framework == FrameworkType.DOTNET_FRAMEWORK


def test_scan_root_with_no_recognizable_source_reports_unknown(tmp_path) -> None:
    """A scan root holding nothing a parser understands still reports Unknown
    -- that case is a genuine detection failure, not a plain-C# project."""
    root = tmp_path / "Empty"
    root.mkdir()
    (root / "readme.txt").write_text("nothing recognizable here", encoding="utf-8")

    detector = ProjectTypeDetector(str(root))
    framework = detector.detect()

    assert framework == FrameworkType.UNKNOWN


def test_required_parsers_by_extension_mounts_union_of_present_view_kinds(tmp_path) -> None:
    """A scan root holding both .aspx and .cshtml mounts both parsers -- the
    old framework-exclusive mapping could only ever pick one."""
    root = tmp_path / "MixedApp"
    root.mkdir()
    (root / "Legacy.cs").write_text("class Legacy {}", encoding="utf-8")
    (root / "Old.aspx").write_text("<%@ Page Language=\"C#\" %>", encoding="utf-8")
    (root / "New.cshtml").write_text("@{ Layout = null; }", encoding="utf-8")

    detector = ProjectTypeDetector(str(root))
    detector.detect()

    assert set(detector.required_parsers_by_extension()) == {
        "csharp_parser",
        "aspx_parser",
        "razor_parser",
    }
    assert set(detector.file_extensions_present()) == {"cs", "aspx", "cshtml"}


def test_required_parsers_by_extension_omits_parsers_for_absent_extensions(tmp_path) -> None:
    root = tmp_path / "CsAndVueOnly"
    root.mkdir()
    (root / "Api.cs").write_text("class Api {}", encoding="utf-8")
    (root / "Widget.vue").write_text("<template></template>", encoding="utf-8")

    detector = ProjectTypeDetector(str(root))
    detector.detect()

    parsers = detector.required_parsers_by_extension()
    assert set(parsers) == {"csharp_parser", "vue_parser"}
    assert "aspx_parser" not in parsers
    assert "razor_parser" not in parsers


# ============================================================
# ProjectScanner: mounting and the Framework Label report
# ============================================================


def test_scanner_raises_clear_error_when_framework_cannot_be_identified(tmp_path) -> None:
    root = tmp_path / "NoMarkers"
    root.mkdir()
    (root / "readme.txt").write_text("nothing recognizable here", encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown"):
        ProjectScanner(project_root=str(root))


def test_scanner_mounts_both_aspx_and_razor_parsers_for_a_mixed_scan_root(tmp_path) -> None:
    """Acceptance: a scan root holding both WebForms pages and Razor views
    parses both, and neither set of view records is missing."""
    root = tmp_path / "MixedApp"
    root.mkdir()
    (root / "Legacy.cs").write_text("public class Legacy {}", encoding="utf-8")
    aspx_path = root / "Old.aspx"
    aspx_path.write_text(
        '<%@ Page Language="C#" %>\n<asp:Label ID="Lbl1" runat="server" Text="Hello" />',
        encoding="utf-8",
    )
    cshtml_path = root / "New.cshtml"
    cshtml_path.write_text("@{ Layout = null; }\n<h1>Hello</h1>", encoding="utf-8")

    scanner = ProjectScanner(project_root=str(root), project_name="MixedApp")

    assert "aspx" in scanner.parsers
    assert "razor" in scanner.parsers
    assert set(scanner.required_parsers) == {
        "csharp_parser",
        "aspx_parser",
        "razor_parser",
    }

    scan_result = ProjectScanResult(
        project_root=str(root), project_name="MixedApp", scan_time=datetime.now()
    )
    scanner.refresh_view_files(scan_result, [str(aspx_path), str(cshtml_path)])

    assert len(scan_result.aspx_results) == 1
    assert len(scan_result.razor_results) == 1


def test_scanner_records_framework_report_on_the_scan_result(tmp_path) -> None:
    """Acceptance: the refresh response carries the Framework Label per scan
    root, together with the parsers that mounted."""
    root = tmp_path / "TTPUR"
    root.mkdir()
    (root / "Web.config").write_text("<configuration></configuration>", encoding="utf-8")
    (root / "Default.aspx").write_text('<%@ Page Language="C#" %>', encoding="utf-8")
    (root / "Default.aspx.cs").write_text("public class Default {}", encoding="utf-8")

    scanner = ProjectScanner(project_root=str(root), project_name="TTPUR")
    scan_result = ProjectScanResult(
        project_root=str(root), project_name="TTPUR", scan_time=datetime.now()
    )
    scanner.refresh_view_files(scan_result, [str(root / "Default.aspx")])
    scanner._record_framework_report()

    assert scan_result.framework_reports == [
        {
            "scan_root": str(root),
            "framework": FrameworkType.WEBFORMS.value,
            "parsers": ["csharp_parser", "aspx_parser"],
        }
    ]

    # A second report for the same scan root replaces, rather than piling
    # onto, the first -- repeated refreshes must not accumulate duplicates.
    scanner._record_framework_report()
    assert len(scan_result.framework_reports) == 1


def test_project_scan_result_pickle_roundtrip_defaults_framework_reports(tmp_path) -> None:
    """A scan result pickled before this ticket landed has no
    `framework_reports` attribute at all; unpickling it must not explode."""
    import pickle

    result = ProjectScanResult(
        project_root=str(tmp_path), project_name="Legacy", scan_time=datetime.now()
    )
    state = result.__getstate__()
    del state["framework_reports"]
    blob = pickle.dumps(state)
    restored_state = pickle.loads(blob)

    restored = ProjectScanResult.__new__(ProjectScanResult)
    restored.__setstate__(restored_state)

    assert restored.framework_reports == []
