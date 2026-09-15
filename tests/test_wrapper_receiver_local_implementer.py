"""Ticket 01 (wrapper-receiver-resolves-through-interface): an interface-typed wrapper receiver
resolves to its unique local implementer.

IQCS calls `_utility.SqlParam(...)` through `IUtilityService`, a field typed as an interface.
`Services/UtilityService.cs`, in the same repository, declares `class UtilityService :
IUtilityService` and implements `SqlParam` itself. Before this ticket, the analyzer never looked
for that class: the call reached Contract Preflight as an unavailable external wrapper receiver
and was reported `unresolved_contract` / `no_contract_matches_receiver_type` -- the same status a
genuinely external, un-vendored library receives.

The primary seam is the real host run against the real IQCS checkout, per this repository's
existing convention for this class of receiver-resolution change (mirrors
`tests/test_wrapper_receiver_declaring_type.py`). The zero/ambiguous/scope-boundary/base-class
cases are exercised against small synthetic scan roots, syntax-only (no compilation needed), since
none of them depend on a real Roslyn-bound symbol.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import CSharpAnalysisGateway, SpCatalog
from code_analyzer.static_analyzer_host import StaticAnalyzerHost

IQCS_ROOT = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "IQCS"
IQCS_SERVICE = IQCS_ROOT / "Services" / "HomeService.cs"

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)
requires_iqcs_fixture = pytest.mark.skipif(
    not IQCS_SERVICE.exists(),
    reason="local data/repos/System_Dept_1/IQCS fixture checkout is not present",
)


def _analyze(target: Path, source_root: Path) -> list[dict]:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    results = host.analyze_csharp_files([target], source_roots=[source_root])
    assert len(results) == 1
    return results[0]["db_invocations"]


def _sql_param_call(invocations: list[dict]) -> dict:
    return next(
        invocation
        for invocation in invocations
        if invocation.get("wrapper_method_name") == "SqlParam"
    )


@requires_dotnet
@requires_iqcs_fixture
def test_interface_wrapper_call_resolves_to_its_local_implementer() -> None:
    """`_utility.SqlParam(...)` is declared through `IUtilityService`. Its only local
    implementer, `UtilityService` (`Services/UtilityService.cs`), declares `SqlParam` itself, so
    the call is reported source-backed and named by that concrete class."""
    call = _sql_param_call(_analyze(IQCS_SERVICE, IQCS_ROOT))

    assert call["wrapper_receiver_type"] == "IUtilityService"
    assert call["wrapper_source_available"] is True
    assert call["receiver_implementation_identity"] == "UtilityService"


@requires_dotnet
@requires_iqcs_fixture
def test_interface_resolved_call_reaches_the_gateway_as_a_source_wrapper() -> None:
    """Ticket 01's Implementation Decisions: the single-implementer case needs no gateway
    change -- the existing `if source_available:` branch in `reconcile_wrapper` already
    classifies `wrapper_source_available=true` facts `source_wrapper`. Before this ticket the
    same call reached `unresolved_contract` / `no_contract_matches_receiver_type`."""
    call = _sql_param_call(_analyze(IQCS_SERVICE, IQCS_ROOT))
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))

    reconciliation = gateway.reconcile_wrapper("HomeService.cs", call)

    assert reconciliation.wrapper_kind == "source_wrapper"
    assert reconciliation.status == "source_wrapper"
    assert reconciliation.status not in {"unresolved_contract", "no_contract_matches_receiver_type"}


IFACE_SOURCE = """
using Microsoft.Data.SqlClient;
namespace IQCS.Interfaces
{
    public interface IUtilityService
    {
        SqlParameter SqlParam(string paramKey, object? value, string? typeName = null);
    }
}
"""

CALLER_SOURCE = """
using IQCS.Interfaces;
using Microsoft.Data.SqlClient;
namespace IQCS.Services
{
    public class Caller
    {
        private readonly IUtilityService _utility;
        public Caller(IUtilityService utility) { _utility = utility; }
        public void Qry()
        {
            var p = _utility.SqlParam("UserID", 1);
        }
    }
}
"""


def _write_fixture(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")


@requires_dotnet
def test_interface_with_no_local_implementer_is_unaffected() -> None:
    """An interface the corpus declares but that no local class implements is left exactly as
    it is reported today -- this ticket adds no new status for that case."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_fixture(root, {
            "IUtilityService.cs": IFACE_SOURCE,
            "Caller.cs": CALLER_SOURCE,
        })
        call = _sql_param_call(_analyze(root / "Caller.cs", root))

    assert call["wrapper_source_available"] is False
    assert call["receiver_implementation_identity"] is None


TIED_IMPLEMENTER_SOURCE = """
using IQCS.Interfaces;
using Microsoft.Data.SqlClient;
namespace IQCS.Services
{{
    public class {class_name} : IUtilityService
    {{
        public SqlParameter SqlParam(string paramKey, object? value, string? typeName = null)
            => new SqlParameter(paramKey, value);
    }}
}}
"""


@requires_dotnet
def test_interface_with_two_local_implementers_is_unaffected_by_this_ticket() -> None:
    """Two or more local implementing classes is, for this ticket, left exactly as it is
    reported today -- ticket 02 turns that case into a distinct, reviewable outcome; this
    ticket must never guess between them by declaration order, file order, or name
    similarity."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_fixture(root, {
            "IUtilityService.cs": IFACE_SOURCE,
            "UtilityServiceA.cs": TIED_IMPLEMENTER_SOURCE.format(class_name="UtilityServiceA"),
            "UtilityServiceB.cs": TIED_IMPLEMENTER_SOURCE.format(class_name="UtilityServiceB"),
            "Caller.cs": CALLER_SOURCE,
        })
        call = _sql_param_call(_analyze(root / "Caller.cs", root))

    assert call["wrapper_source_available"] is False
    assert call["receiver_implementation_identity"] is None


@requires_dotnet
def test_implementer_search_is_bounded_to_the_current_scan_root() -> None:
    """A class in an unrelated sibling root of a multi-root system is never treated as this
    root's Local Implementer, mirroring the existing Source-wrapper resolution boundary."""
    with tempfile.TemporaryDirectory() as temp_dir:
        scan_root = Path(temp_dir) / "scan_root"
        sibling_root = Path(temp_dir) / "sibling_root"
        scan_root.mkdir()
        sibling_root.mkdir()
        _write_fixture(scan_root, {
            "IUtilityService.cs": IFACE_SOURCE,
            "Caller.cs": CALLER_SOURCE,
        })
        _write_fixture(sibling_root, {
            "UtilityService.cs": TIED_IMPLEMENTER_SOURCE.format(class_name="UtilityService"),
        })

        call = _sql_param_call(_analyze(scan_root / "Caller.cs", scan_root))

    assert call["wrapper_source_available"] is False
    assert call["receiver_implementation_identity"] is None


BASE_IMPLEMENTER_SOURCE = """
using IQCS.Interfaces;
using Microsoft.Data.SqlClient;
namespace IQCS.Services
{
    public abstract class UtilityServiceBase : IUtilityService
    {
        public SqlParameter SqlParam(string paramKey, object? value, string? typeName = null)
            => new SqlParameter(paramKey, value);
    }
}
"""

CONCRETE_SUBCLASS_SOURCE = """
namespace IQCS.Services
{
    public class UtilityService : UtilityServiceBase
    {
    }
}
"""


@requires_dotnet
def test_implementer_reached_only_through_a_base_class_still_counts() -> None:
    """A class that implements the interface only through a further base class still counts as
    a valid Local Implementer, provided it (or that base) declares the called method -- the
    common 'abstract base implements most of the interface, concrete subclass fills in the
    rest' pattern is not silently excluded. The abstract base itself is never reported as the
    implementer: a DI container can never hand back an instance of it."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_fixture(root, {
            "IUtilityService.cs": IFACE_SOURCE,
            "UtilityServiceBase.cs": BASE_IMPLEMENTER_SOURCE,
            "UtilityService.cs": CONCRETE_SUBCLASS_SOURCE,
            "Caller.cs": CALLER_SOURCE,
        })
        call = _sql_param_call(_analyze(root / "Caller.cs", root))

    assert call["wrapper_source_available"] is True
    assert call["receiver_implementation_identity"] == "UtilityService"


IFACE_RUN_SOURCE = """
namespace App
{
    public interface IFooService
    {
        void Run(string sql);
    }
}
"""

# `Base` implements `IFooService` but declares nothing; `Concrete` (two hops from the interface)
# is where `Run` is actually declared, and its body reaches a terminal sink. This is deliberately
# a different shape from `test_implementer_reached_only_through_a_base_class_still_counts` above:
# there, no WrapperDefinition existed anywhere for `SqlParam` (it never touches a command
# object), so the call could only ever be resolved by this ticket's own logic. Here `Run` *does*
# reach a sink, so a WrapperDefinition already exists for `Concrete.Run` -- this exercises the
# redirect onto that existing definition's own method-semantics/terminal-sink facts, the same
# facts a directly-typed local wrapper reaching `Concrete.Run` already reports.
TWO_HOP_BASE_SOURCE = """
namespace App
{
    public class Base : IFooService
    {
    }
}
"""

TWO_HOP_CONCRETE_SOURCE = """
using Microsoft.Data.SqlClient;
namespace App
{
    public class Concrete : Base
    {
        private readonly SqlConnection _conn;
        public Concrete(SqlConnection conn) { _conn = conn; }
        public void Run(string sql)
        {
            var cmd = new SqlCommand(sql, _conn);
            cmd.ExecuteNonQuery();
        }
    }
}
"""

TWO_HOP_CALLER_SOURCE = """
namespace App
{
    public class Caller
    {
        private readonly IFooService _foo;
        public Caller(IFooService foo) { _foo = foo; }
        public void Do()
        {
            _foo.Run("usp_Thing");
        }
    }
}
"""


@requires_dotnet
def test_local_implementer_reached_through_two_base_hops_reuses_its_wrapper_definition() -> None:
    """`Concrete` implements `IFooService` only through `Base`, which itself implements nothing
    of the interface -- the same "further base class" pattern as the SqlParam-shaped test above,
    but here `Concrete.Run` reaches a terminal sink and so already has a scanned
    WrapperDefinition. Per the spec's Implementation Decisions, redirecting to it reuses the
    existing extraction rather than leaving these facts blank."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_fixture(root, {
            "IFooService.cs": IFACE_RUN_SOURCE,
            "Base.cs": TWO_HOP_BASE_SOURCE,
            "Concrete.cs": TWO_HOP_CONCRETE_SOURCE,
            "Caller.cs": TWO_HOP_CALLER_SOURCE,
        })
        invocations = _analyze(root / "Caller.cs", root)
        call = next(i for i in invocations if i.get("wrapper_method_name") == "Run")

    assert call["wrapper_source_available"] is True
    assert call["receiver_implementation_identity"] == "Concrete"
    assert call["wrapper_method_semantics"] == "fixed_inline_sql"
    assert call["wrapper_terminal_sink"] == "ExecuteNonQuery"
    assert call["wrapper_reaches_stored_procedure_sink"] is True
