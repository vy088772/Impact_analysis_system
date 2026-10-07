"""ADR-0044: the analyzer host records the Bound Call Target of each call.

The seam is the real host run. A synthetic source with no project file checks the
receiver kinds and the Local Implementer rule through the source-only compilation. The
RTTalentDB fixture checks the same through the real project compilation.
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

from code_analyzer.static_analyzer_host import StaticAnalyzerHost
from config.settings import settings
from service import scan_store
from service.call_graph_nodes import MethodNodes

RTTALENT_ROOT = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "RTTalentDB" / "RTTalentDB"
RTTALENT_CONTROLLER = RTTALENT_ROOT / "Controllers" / "JobTypeController.cs"

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)
requires_rttalent_fixture = pytest.mark.skipif(
    not RTTALENT_CONTROLLER.exists(),
    reason="local data/repos/System_Dept_1/RTTalentDB fixture checkout is not present",
)

SOURCE = """
using System.Collections.Generic;
using System.Linq;

public interface IJobService { void Invalidate(int id); void Invalidate(string id); }
public interface IShared { void Run(); }
public interface IOrphan { void Lost(); }

public class JobService : IJobService
{
    public void Invalidate(int id) { Helper.Go(); }
    public void Invalidate(string id) { }
}
public class SharedA : IShared { public void Run() { } }
public class SharedB : IShared { public void Run() { } }

public abstract class BaseRepo { public void Save() { } }
public interface IRepo { void Save(); }
public class Repo : BaseRepo, IRepo { }

public static class Helper
{
    public static void Go() { }
    public static int Twice(this int value) => value * 2;
}

public class Controller(IJobService _primary)
{
    private readonly IJobService _field;
    public IJobService Prop { get; }
    private readonly IShared _shared;
    private readonly IOrphan _orphan;
    private readonly IRepo _repo;

    public void Act()
    {
        _primary.Invalidate(1);
        _field.Invalidate(2);
        Prop.Invalidate("3");
        IJobService local = new JobService();
        local.Invalidate(4);
        _shared.Run();
        _orphan.Lost();
        _repo.Save();
        var doubled = 5.Twice();
        System.Console.WriteLine("framework");
        new List<int>().Select(x => x).ToList();
        Other(unknownSymbol);
    }

    private void Other(object value) { }
}
"""


def _calls_by_method(result: dict) -> dict[str, list[dict]]:
    """The calls of each method by its simple names (`Class.Method`); this helper merges overloads."""
    calls: dict[str, list[dict]] = {}
    for method in result["methods"]:
        if method["class_name"]:
            calls.setdefault(f"{method['class_name']}.{method['method_name']}", []).extend(method["calls"])
    return calls


def _targets(calls: list[dict]) -> list[tuple[str, str, str]]:
    return [
        (call["call_text"], f"{call['target_class']}.{call['target_method']}", call["unresolved_reason"])
        for call in calls
    ]


@pytest.fixture(scope="module")
def synthetic_calls() -> dict[str, list[dict]]:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "Controller.cs"
        source_path.write_text(SOURCE, encoding="utf-8")
        return _calls_by_method(host.analyze_csharp(source_path))


@requires_dotnet
def test_a_call_through_a_field_a_primary_constructor_parameter_a_property_and_a_local_binds(
    synthetic_calls,
) -> None:
    targets = _targets(synthetic_calls["Controller.Act"])

    assert ("_primary.Invalidate", "JobService.Invalidate", "") in targets  # primary constructor
    assert ("_field.Invalidate", "JobService.Invalidate", "") in targets  # field
    assert ("Prop.Invalidate", "JobService.Invalidate", "") in targets  # property, string overload
    assert ("local.Invalidate", "JobService.Invalidate", "") in targets  # local variable


@requires_dotnet
def test_an_interface_with_one_local_implementer_binds_to_the_implementer(synthetic_calls) -> None:
    assert ("Helper.Go", "Helper.Go", "") in _targets(synthetic_calls["JobService.Invalidate"])
    assert ("_primary.Invalidate", "JobService.Invalidate", "") in _targets(synthetic_calls["Controller.Act"])


@requires_dotnet
def test_an_implementer_that_inherits_the_method_binds_to_the_declaring_base(synthetic_calls) -> None:
    assert ("_repo.Save", "BaseRepo.Save", "") in _targets(synthetic_calls["Controller.Act"])


@requires_dotnet
def test_an_interface_with_no_or_two_local_implementers_has_no_target(synthetic_calls) -> None:
    calls = {call["call_text"]: call for call in synthetic_calls["Controller.Act"]}

    assert calls["_shared.Run"]["target_method"] == ""
    assert calls["_shared.Run"]["unresolved_reason"] == "ambiguous_implementation"
    assert calls["_shared.Run"]["candidate_classes"] == ["SharedA", "SharedB"]
    assert calls["_orphan.Lost"]["target_method"] == ""
    assert calls["_orphan.Lost"]["unresolved_reason"] == "no_local_implementer"


@requires_dotnet
def test_an_extension_method_and_an_unbound_argument_still_bind(synthetic_calls) -> None:
    targets = _targets(synthetic_calls["Controller.Act"])

    assert ("5.Twice", "Helper.Twice", "") in targets
    assert ("Other", "Controller.Other", "") in targets


@requires_dotnet
def test_a_call_into_a_framework_method_is_not_recorded(synthetic_calls) -> None:
    call_texts = [call["call_text"] for call in synthetic_calls["Controller.Act"]]

    assert "System.Console.WriteLine" not in call_texts
    assert not any("Select" in text or "ToList" in text for text in call_texts)


NODE_SOURCE = """
using System.Collections.Generic;

namespace A { public class Svc { public void Run() { } } }
namespace B { public class Svc { public void Run() { } } }

namespace Shop
{
    public record Money(int Cents) { public int Twice() => Cents * 2; }
    public struct Point { public int Sum() => 0; }

    public class Outer { public class Inner { public void Deep(ref int value, List<string> names) { } } }

    public class Store
    {
        public void Save(int id) { }
        public void Save(string id) { }
        public void Get() { }
        public void Get<TModel>() { }
    }

    public interface IStore { void Save(int id); void Save(string id); }
    public class LocalStore : IStore
    {
        public void Save(int id) { }
        public void Save(string id) { }
    }

    public class Page
    {
        private readonly IStore _store;

        public void Act()
        {
            new Store().Save(1);
            new Store().Save("1");
            new Store().Get();
            new Store().Get<int>();
            new A.Svc().Run();
            new B.Svc().Run();
            new Money(1).Twice();
            new Point().Sum();
            var value = 0;
            new Outer.Inner().Deep(ref value, new List<string>());
            _store.Save("2");
        }
    }
}
"""


@pytest.fixture(scope="module")
def node_result() -> dict:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "Nodes.cs"
        source_path.write_text(NODE_SOURCE, encoding="utf-8")
        return host.analyze_csharp(source_path)


@requires_dotnet
def test_each_method_span_carries_its_bound_method_node(node_result) -> None:
    """ADR-0044: a node is the bound method symbol, so overloads, generic arity and namespaces stay apart."""
    spans = {(method["class_name"], method["node"]) for method in node_result["methods"]}

    assert ("Store", "Shop.Store.Save(int)") in spans
    assert ("Store", "Shop.Store.Save(string)") in spans
    assert ("Store", "Shop.Store.Get()") in spans
    assert ("Store", "Shop.Store.Get`1()") in spans
    assert ("Svc", "A.Svc.Run()") in spans
    assert ("Svc", "B.Svc.Run()") in spans
    # A record, a struct and a nested class each get their real class.
    assert ("Money", "Shop.Money.Twice()") in spans
    assert ("Point", "Shop.Point.Sum()") in spans
    assert ("Inner", "Shop.Outer.Inner.Deep(ref int,System.Collections.Generic.List<string>)") in spans


@requires_dotnet
def test_each_bound_call_target_names_the_node_of_its_overload(node_result) -> None:
    [act] = [method for method in node_result["methods"] if method["node"] == "Shop.Page.Act()"]
    targets = [(call["call_text"], call["target_node"]) for call in act["calls"]]

    assert targets == [
        ("new Store().Save", "Shop.Store.Save(int)"),
        ("new Store().Save", "Shop.Store.Save(string)"),
        ("new Store().Get", "Shop.Store.Get()"),
        ("new Store().Get<int>", "Shop.Store.Get`1()"),
        ("new A.Svc().Run", "A.Svc.Run()"),
        ("new B.Svc().Run", "B.Svc.Run()"),
        ("new Money(1).Twice", "Shop.Money.Twice()"),
        ("new Point().Sum", "Shop.Point.Sum()"),
        ("new Outer.Inner().Deep", "Shop.Outer.Inner.Deep(ref int,System.Collections.Generic.List<string>)"),
        # An interface call binds to the overload of its Local Implementer.
        ("_store.Save", "Shop.LocalStore.Save(string)"),
    ]


@requires_dotnet
def test_a_scan_keeps_each_bound_call_target_in_the_scan_cache(tmp_path: Path) -> None:
    """The record goes from the host through the scan into the C# scan cache, and back."""
    root = tmp_path / "project"
    (root / "Services").mkdir(parents=True)
    (root / "OrderPage.cs").write_text(
        "public class OrderPage { private readonly IOrderService _orders;"
        " public void Save() { _orders.Store(); } }",
        encoding="utf-8",
    )
    (root / "Services" / "OrderService.cs").write_text(
        "public interface IOrderService { void Store(); }"
        " public class OrderService : IOrderService { public void Store() { } }",
        encoding="utf-8",
    )
    previous_cache_root = settings.SCAN_CACHE_ROOT
    settings.SCAN_CACHE_ROOT = str(tmp_path / "cache")
    try:
        scan_store.get_or_scan(root, refresh=True)
        scan_store._mem_cache.clear()
        cached = scan_store.get_or_scan(root, refresh=False)
    finally:
        scan_store.clear_cache(root)
        settings.SCAN_CACHE_ROOT = previous_cache_root

    [save] = cached.source_snapshots["OrderPage.cs"].method_spans
    assert save.node == "OrderPage.Save()"
    assert [(call.call_text, call.bound_target) for call in save.calls] == [
        ("_orders.Store", "OrderService.Store()")
    ]


@requires_dotnet
def test_a_database_invocation_its_method_span_and_a_call_target_give_one_node(tmp_path: Path) -> None:
    """ADR-0044: the invocation joins by the span that holds it, not by its class and method names."""
    root = tmp_path / "project"
    root.mkdir()
    # `Db.Exec` takes the procedure from its caller, so the invocation of `usp_Save_Code`
    # is the call in `Save(string)`.
    (root / "Store.cs").write_text(
        "using System.Data;\n"
        "using System.Data.SqlClient;\n"
        "namespace Shop {\n"
        "public static class Db {\n"
        "  public static void Exec(string procedure) {\n"
        "    var command = new SqlCommand(procedure, new SqlConnection(\"x\"));\n"
        "    command.CommandType = CommandType.StoredProcedure;\n"
        "    command.ExecuteNonQuery();\n"
        "  }\n"
        "}\n"
        "public class Store {\n"
        "  public void Save(int id) { }\n"
        "  public void Save(string code) { Db.Exec(\"dbo.usp_Save_Code\"); }\n"
        "}\n"
        "public class Page { public void Act() { new Store().Save(\"1\"); } }\n"
        "}\n",
        encoding="utf-8",
    )
    previous_cache_root = settings.SCAN_CACHE_ROOT
    settings.SCAN_CACHE_ROOT = str(tmp_path / "cache")
    try:
        scan = scan_store.get_or_scan(root, refresh=True)
    finally:
        scan_store.clear_cache(root)
        settings.SCAN_CACHE_ROOT = previous_cache_root

    spans = {span.node: span for span in scan.source_snapshots["Store.cs"].method_spans}
    [invocation] = [
        item
        for items in scan.db_invocations.values()
        for item in items
        if item["command_text"] == "dbo.usp_Save_Code"
    ]
    [call] = spans["Shop.Page.Act()"].calls

    node = MethodNodes(scan).at_offset("Store.cs", invocation["start_offset"])
    assert node == "Shop.Store.Save(string)"
    assert node in spans
    assert call.bound_target == node


@requires_dotnet
@requires_rttalent_fixture
def test_the_rttalentdb_jobtype_action_binds_to_the_service_implementation() -> None:
    """`JobTypeController(IJobTypeService _service)` calls `_service.InvalidateJobType`. The one
    Local Implementer of `IJobTypeService` is `JobTypeService`."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    [result] = host.analyze_csharp_files([RTTALENT_CONTROLLER], source_roots=[RTTALENT_ROOT])

    calls = _calls_by_method(result)["JobTypeController.JobTypeInvalid"]

    assert ("_service.InvalidateJobType", "JobTypeService.InvalidateJobType", "") in _targets(calls)
