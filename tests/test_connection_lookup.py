"""Tests for the Connection Lookup (Seam A, step 1).

The Connection Lookup answers one question: which connection does a lookup key
open for one source file. Each test builds project files and configuration
files in a temporary directory, gets the view of one source file, and checks
the answer.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.connection_lookup import (
    APP_SETTINGS,
    CONNECTION_STRINGS,
    ConnectionAnswer,
    ConnectionLookup,
    ContextRegistration,
    ROOT_CONFIGURATION,
)
from code_analyzer.parent_application import AMBIGUOUS_PARENT_APPLICATION


def _write_project(directory: Path) -> Path:
    """Write a project file into a directory. Give back the directory."""
    directory.mkdir(parents=True, exist_ok=True)
    project_file = directory / f"{directory.name}.csproj"
    project_file.write_text("<Project></Project>", encoding="utf-8")
    return directory


def _write_web_config(
    directory: Path, *, connection_strings: dict = None, app_settings: dict = None
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    names = "".join(
        f'<add name="{name}" connectionString="{value}"/>'
        for name, value in (connection_strings or {}).items()
    )
    keys = "".join(
        f'<add key="{key}" value="{value}"/>'
        for key, value in (app_settings or {}).items()
    )
    path = directory / "Web.config"
    path.write_text(
        "<configuration>"
        f"<appSettings>{keys}</appSettings>"
        f"<connectionStrings>{names}</connectionStrings>"
        "</configuration>",
        encoding="utf-8",
    )
    return path


def _write_application_settings(
    directory: Path, *, connection_strings: dict, root: dict = None
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    document = {"ConnectionStrings": dict(connection_strings)}
    document.update(root or {})
    path = directory / "appsettings.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _source_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("// source\n", encoding="utf-8")
    return path


def test_a_source_file_uses_the_web_config_beside_its_nearest_project_file(
    tmp_path: Path,
):
    shop = _write_project(tmp_path / "Shop")
    _write_web_config(
        shop, connection_strings={"PUR": "Server=sql01;Database=PurchaseDb;uid=u;pwd=p"}
    )
    source = _source_file(shop / "Pages" / "Order.aspx.cs")

    answer = ConnectionLookup(tmp_path).for_file(source).lookup("PUR", CONNECTION_STRINGS)

    assert answer == ConnectionAnswer(
        database="PurchaseDb",
        server="sql01",
        declared_in="Shop/Web.config",
        reason="",
    )


def test_two_projects_under_one_scan_root_resolve_one_key_to_their_own_database(
    tmp_path: Path,
):
    shop = _write_project(tmp_path / "Shop")
    _write_web_config(shop, connection_strings={"Main": "Server=sql01;Database=ShopDb"})
    depot = _write_project(tmp_path / "Depot")
    _write_web_config(depot, connection_strings={"Main": "Server=sql02;Database=DepotDb"})
    lookup = ConnectionLookup(tmp_path)

    shop_answer = lookup.for_file(_source_file(shop / "Order.cs")).lookup(
        "Main", CONNECTION_STRINGS
    )
    depot_answer = lookup.for_file(_source_file(depot / "Stock.cs")).lookup(
        "Main", CONNECTION_STRINGS
    )

    assert (shop_answer.database, shop_answer.declared_in) == ("ShopDb", "Shop/Web.config")
    assert (depot_answer.database, depot_answer.declared_in) == (
        "DepotDb",
        "Depot/Web.config",
    )


def test_a_project_with_no_configuration_file_uses_the_web_config_of_the_scan_root(
    tmp_path: Path,
):
    _write_web_config(tmp_path, app_settings={"STC": "Server=sql01;Database=StcDb"})
    library = _write_project(tmp_path / "Library")
    source = _source_file(library / "Data" / "Reader.cs")

    answer = ConnectionLookup(tmp_path).for_file(source).lookup("STC", APP_SETTINGS)

    assert answer == ConnectionAnswer(
        database="StcDb", server="sql01", declared_in="Web.config", reason=""
    )


def test_two_first_level_directories_with_a_web_config_give_the_first_in_name_order(
    tmp_path: Path,
):
    _write_web_config(tmp_path / "Beta", connection_strings={"Main": "Server=b;Database=BetaDb"})
    _write_web_config(tmp_path / "Alpha", connection_strings={"Main": "Server=a;Database=AlphaDb"})
    library = _write_project(tmp_path / "Library")
    source = _source_file(library / "Reader.cs")

    answer = ConnectionLookup(tmp_path).for_file(source).lookup("Main", CONNECTION_STRINGS)

    assert (answer.database, answer.declared_in) == ("AlphaDb", "Alpha/Web.config")


def test_the_web_config_in_the_scan_root_directory_wins_over_a_first_level_directory(
    tmp_path: Path,
):
    _write_web_config(tmp_path / "Alpha", connection_strings={"Main": "Server=a;Database=AlphaDb"})
    _write_web_config(tmp_path, connection_strings={"Main": "Server=r;Database=RootDb"})
    source = _source_file(_write_project(tmp_path / "Library") / "Reader.cs")

    answer = ConnectionLookup(tmp_path).for_file(source).lookup("Main", CONNECTION_STRINGS)

    assert (answer.database, answer.declared_in) == ("RootDb", "Web.config")


def test_a_source_file_with_no_project_file_uses_the_web_config_of_the_scan_root(
    tmp_path: Path,
):
    _write_web_config(tmp_path, connection_strings={"Main": "Server=r;Database=RootDb"})
    source = _source_file(tmp_path / "App_Code" / "Helper.cs")

    view = ConnectionLookup(tmp_path).for_file(source)

    assert view.lookup("Main", CONNECTION_STRINGS).database == "RootDb"
    assert view.reads_application_settings_file is False


def test_a_source_file_with_no_table_gets_the_key_as_name_guess(tmp_path: Path):
    library = _write_project(tmp_path / "Library")
    source = _source_file(library / "Reader.cs")

    answer = ConnectionLookup(tmp_path).for_file(source).lookup("PUR", CONNECTION_STRINGS)

    assert answer == ConnectionAnswer(
        database="PUR", server=None, declared_in=None, reason=""
    )


def test_a_web_config_table_that_is_empty_in_both_namespaces_gives_the_guess(
    tmp_path: Path,
):
    shop = _write_project(tmp_path / "Shop")
    _write_web_config(shop, app_settings={"MailHost": "smtp.example.com"})
    _write_web_config(tmp_path, connection_strings={"PUR": "Server=r;Database=RootDb"})
    source = _source_file(shop / "Order.cs")

    answer = ConnectionLookup(tmp_path).for_file(source).lookup("PUR", CONNECTION_STRINGS)

    assert answer == ConnectionAnswer(database="PUR")


def test_a_failed_lookup_on_the_web_config_path_has_no_reason(tmp_path: Path):
    shop = _write_project(tmp_path / "Shop")
    _write_web_config(shop, app_settings={"PUR": "Server=sql01;Database=PurchaseDb"})
    view = ConnectionLookup(tmp_path).for_file(_source_file(shop / "Order.cs"))

    missing_key = view.lookup("HR", APP_SETTINGS)
    other_namespace = view.lookup("PUR", CONNECTION_STRINGS)

    assert missing_key == ConnectionAnswer()
    assert other_namespace == ConnectionAnswer()


def test_a_project_with_an_application_settings_file_and_a_web_config_uses_the_settings_file(
    tmp_path: Path,
):
    core = _write_project(tmp_path / "Core")
    _write_application_settings(
        core, connection_strings={"Main": "Server=sql01;Database=SettingsDb;User Id=u;Password=p"}
    )
    _write_web_config(core, connection_strings={"Main": "Server=sql02;Database=WebConfigDb"})
    view = ConnectionLookup(tmp_path).for_file(_source_file(core / "Data" / "Repository.cs"))

    assert view.lookup("Main", CONNECTION_STRINGS) == ConnectionAnswer(
        database="SettingsDb",
        server="sql01",
        declared_in="Core/appsettings.json",
        reason="",
    )
    assert view.reads_application_settings_file is True


def test_a_failed_lookup_in_an_application_settings_file_states_a_reason(
    tmp_path: Path,
):
    core = _write_project(tmp_path / "Core")
    _write_application_settings(
        core,
        connection_strings={"Main": "Server=sql01;Database=MainDb"},
        root={"Legacy": "Server=sql09;Database=LegacyDb"},
    )
    view = ConnectionLookup(tmp_path).for_file(_source_file(core / "Repository.cs"))

    assert view.lookup("Missing", CONNECTION_STRINGS) == ConnectionAnswer(
        reason="connection_key_not_in_project_scope"
    )
    assert view.lookup("Legacy", CONNECTION_STRINGS) == ConnectionAnswer(
        reason="root_configuration_namespace_not_connection_strings"
    )
    assert view.lookup("Main", ROOT_CONFIGURATION) == ConnectionAnswer(
        reason="root_configuration_namespace_not_connection_strings"
    )


def test_a_source_file_with_no_project_file_has_no_table_when_the_scan_root_holds_a_settings_file(
    tmp_path: Path,
):
    core = _write_project(tmp_path / "Core")
    _write_application_settings(core, connection_strings={"Main": "Server=s;Database=MainDb"})
    _write_web_config(tmp_path, connection_strings={"Main": "Server=r;Database=RootDb"})
    view = ConnectionLookup(tmp_path).for_file(_source_file(tmp_path / "loose" / "Orphan.cs"))

    assert view.lookup("Main", CONNECTION_STRINGS) == ConnectionAnswer(
        reason="no_project_connection_scope"
    )
    assert view.context_registration("MainContext") == ContextRegistration(
        reason="no_project_connection_scope"
    )
    assert view.reads_application_settings_file is True


def test_a_project_with_no_configuration_file_uses_the_scan_root_web_config_beside_a_core_project(
    tmp_path: Path,
):
    core = _write_project(tmp_path / "Core")
    _write_application_settings(core, connection_strings={"Main": "Server=s;Database=MainDb"})
    _write_web_config(tmp_path, connection_strings={"Main": "Server=r;Database=RootDb"})
    library = _write_project(tmp_path / "Library")
    view = ConnectionLookup(tmp_path).for_file(_source_file(library / "Reader.cs"))

    assert view.lookup("Main", CONNECTION_STRINGS).database == "RootDb"
    assert view.reads_application_settings_file is False


def test_the_view_answers_the_context_connection_registration_of_a_context_type(
    tmp_path: Path,
):
    core = _write_project(tmp_path / "Core")
    _write_application_settings(core, connection_strings={"Main": "Server=s;Database=MainDb"})
    (core / "Program.cs").write_text(
        "builder.Services.AddDbContext<OrdersContext>(options =>\n"
        '    options.UseSqlServer(builder.Configuration.GetConnectionString("Main")));\n',
        encoding="utf-8",
    )
    view = ConnectionLookup(tmp_path).for_file(_source_file(core / "Repository.cs"))

    assert view.registered_context_types == ("OrdersContext",)
    assert view.context_registration("OrdersContext") == ContextRegistration(
        lookup_key="Main"
    )
    assert view.context_registration("BillingContext") == ContextRegistration(
        reason="context_type_not_registered"
    )


def test_the_view_answers_whether_a_configuration_root_namespace_key_names_a_connection(
    tmp_path: Path,
):
    core = _write_project(tmp_path / "Core")
    _write_application_settings(
        core,
        connection_strings={"Main": "Server=s;Database=MainDb"},
        root={"Legacy": "Server=sql09;Database=LegacyDb", "LogLevel": "Warning"},
    )
    view = ConnectionLookup(tmp_path).for_file(_source_file(core / "Repository.cs"))

    assert view.names_a_connection("legacy") is True
    assert view.names_a_connection("Main") is True
    assert view.names_a_connection("LogLevel") is False


def test_the_application_settings_file_answers_are_empty_on_the_web_config_path(
    tmp_path: Path,
):
    shop = _write_project(tmp_path / "Shop")
    _write_web_config(shop, connection_strings={"Main": "Server=sql01;Database=ShopDb"})
    view = ConnectionLookup(tmp_path).for_file(_source_file(shop / "Order.cs"))

    assert view.registered_context_types == ()
    assert view.context_registration("OrdersContext") == ContextRegistration()
    assert view.names_a_connection("Main") is False
    assert view.reads_application_settings_file is False


def test_the_connection_lookup_reports_each_environment_settings_override(
    tmp_path: Path,
):
    core = _write_project(tmp_path / "Core")
    _write_application_settings(core, connection_strings={"Main": "Server=s;Database=MainDb"})
    (core / "appsettings.Production.json").write_text(
        json.dumps({"ConnectionStrings": {"Main": "Server=p;Database=ProdDb"}}),
        encoding="utf-8",
    )
    lookup = ConnectionLookup(tmp_path)
    view = lookup.for_file(_source_file(core / "Repository.cs"))

    assert view.lookup("Main", CONNECTION_STRINGS).database == "MainDb"
    assert lookup.environment_overrides() == [
        {
            "kind": "environment_settings_override",
            "settings_file": str(core / "appsettings.Production.json"),
            "lookup_key": "Main",
            "database": "ProdDb",
            "server": "p",
            "applied": False,
        }
    ]


def test_the_search_for_the_nearest_project_file_has_no_upper_bound(tmp_path: Path):
    shop = _write_project(tmp_path / "Shop")
    _write_web_config(shop, connection_strings={"Main": "Server=sql01;Database=ShopDb"})
    scan_root = shop / "Pages"
    source = _source_file(scan_root / "Order.aspx.cs")

    answer = ConnectionLookup(scan_root).for_file(source).lookup("Main", CONNECTION_STRINGS)

    assert (answer.database, answer.declared_in) == ("ShopDb", "../Web.config")


def test_a_web_config_that_is_not_readable_as_text_gives_the_guess(tmp_path: Path):
    shop = _write_project(tmp_path / "Shop")
    (shop / "Web.config").write_bytes(b"<configuration>\xa4\xa4\xff</configuration>")
    source = _source_file(shop / "Order.cs")

    answer = ConnectionLookup(tmp_path).for_file(source).lookup("PUR", CONNECTION_STRINGS)

    assert answer == ConnectionAnswer(database="PUR")


def test_the_view_finds_a_lookup_key_and_a_web_config_with_no_regard_to_case(
    tmp_path: Path,
):
    shop = _write_project(tmp_path / "Shop")
    written = _write_web_config(shop, app_settings={"Pur": "Server=sql01;Database=PurchaseDb"})
    written.rename(shop / "web.config")
    source = _source_file(shop / "Order.cs")

    answer = ConnectionLookup(tmp_path).for_file(source).lookup("PUR", APP_SETTINGS)

    assert (answer.database, answer.declared_in) == ("PurchaseDb", "Shop/web.config")


# ---------------------------------------------------------------------------
# Step 2: the Parent Application rule (ticket 05)
# ---------------------------------------------------------------------------


def _write_web_project(directory: Path, iis_url: str = "") -> Path:
    """Write a project file that declares an IIS URL. Give back the directory."""
    directory.mkdir(parents=True, exist_ok=True)
    extension = (
        "<ProjectExtensions><VisualStudio><FlavorProperties GUID=\"x\">"
        f"<WebProjectProperties><IISUrl>{iis_url}</IISUrl></WebProjectProperties>"
        "</FlavorProperties></VisualStudio></ProjectExtensions>"
        if iis_url
        else ""
    )
    (directory / f"{directory.name}.csproj").write_text(
        '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">'
        f"{extension}</Project>",
        encoding="utf-8",
    )
    return directory


def _clone(tmp_path: Path) -> Path:
    """Mark a temporary directory as the root of a repository clone."""
    (tmp_path / ".git").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _lookup(scan_root: Path, source: Path, key: str, namespace: str = CONNECTION_STRINGS):
    return ConnectionLookup(scan_root).for_file(source).lookup(key, namespace)


def test_a_child_application_resolves_a_key_that_only_its_parent_declares(tmp_path: Path):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://localhost/Site")
    _write_web_config(parent, connection_strings={"PUR": "Server=sql01;Database=PurDb"})
    child = _write_web_project(tmp_path / "Site" / "Response", "http://localhost/Site/Response")
    _write_web_config(child, connection_strings={"Other": "Server=sql01;Database=OtherDb"})
    source = _source_file(child / "Response.Master.cs")

    answer = _lookup(tmp_path, source, "PUR")

    assert answer == ConnectionAnswer(
        database="PurDb", server="sql01", declared_in="Site/Web.config"
    )


def test_a_child_application_with_no_web_config_inherits_from_its_parent(tmp_path: Path):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://localhost/Site")
    _write_web_config(parent, connection_strings={"PUR": "Server=sql01;Database=PurDb"})
    child = _write_web_project(tmp_path / "Child", "http://localhost/Site/Child")
    source = _source_file(child / "Page.cs")

    # The child has no Web.config, so the Web.config of the scan root is the
    # table. The scan root is the parent here.
    answer = _lookup(parent, source, "PUR")

    assert (answer.database, answer.declared_in) == ("PurDb", "Site/Web.config")


def test_the_own_declaration_wins_over_the_declaration_of_the_parent(tmp_path: Path):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://localhost/Site")
    _write_web_config(parent, connection_strings={"PUR": "Server=sql01;Database=ParentDb"})
    child = _write_web_project(tmp_path / "Site" / "Response", "http://localhost/Site/Response")
    _write_web_config(child, connection_strings={"PUR": "Server=sql02;Database=ChildDb"})
    source = _source_file(child / "Response.Master.cs")

    answer = _lookup(tmp_path, source, "PUR")

    assert answer == ConnectionAnswer(
        database="ChildDb", server="sql02", declared_in="Site/Response/Web.config"
    )


def test_a_three_level_chain_resolves_through_the_grandparent(tmp_path: Path):
    _clone(tmp_path)
    root = _write_web_project(tmp_path / "Root", "http://host/Root")
    _write_web_config(root, connection_strings={"PUR": "Server=s;Database=RootDb"})
    middle = _write_web_project(tmp_path / "Middle", "http://host/Root/Middle")
    _write_web_config(middle, connection_strings={"Other": "Server=s;Database=MiddleDb"})
    leaf = _write_web_project(tmp_path / "Leaf", "http://host/Root/Middle/Leaf")
    source = _source_file(leaf / "Page.cs")
    _write_web_config(leaf, connection_strings={"Mine": "Server=s;Database=LeafDb"})

    answer = _lookup(tmp_path, source, "PUR")

    assert (answer.database, answer.declared_in) == ("RootDb", "Root/Web.config")


def test_the_nearest_ancestor_wins_when_two_ancestors_declare_the_same_key(tmp_path: Path):
    _clone(tmp_path)
    root = _write_web_project(tmp_path / "Root", "http://host/Root")
    _write_web_config(root, connection_strings={"PUR": "Server=s;Database=RootDb"})
    middle = _write_web_project(tmp_path / "Middle", "http://host/Root/Middle")
    _write_web_config(middle, connection_strings={"PUR": "Server=s;Database=MiddleDb"})
    leaf = _write_web_project(tmp_path / "Leaf", "http://host/Root/Middle/Leaf")
    _write_web_config(leaf, connection_strings={"Mine": "Server=s;Database=LeafDb"})
    source = _source_file(leaf / "Page.cs")

    answer = _lookup(tmp_path, source, "PUR")

    assert (answer.database, answer.declared_in) == ("MiddleDb", "Middle/Web.config")


def test_an_ancestor_with_no_web_config_does_not_stop_the_chain(tmp_path: Path):
    _clone(tmp_path)
    root = _write_web_project(tmp_path / "Root", "http://host/Root")
    _write_web_config(root, connection_strings={"PUR": "Server=s;Database=RootDb"})
    _write_web_project(tmp_path / "Middle", "http://host/Root/Middle")
    leaf = _write_web_project(tmp_path / "Leaf", "http://host/Root/Middle/Leaf")
    _write_web_config(leaf, connection_strings={"Mine": "Server=s;Database=LeafDb"})
    source = _source_file(leaf / "Page.cs")

    assert _lookup(tmp_path, source, "PUR").database == "RootDb"


def test_connection_strings_inherit_only_from_connection_strings(tmp_path: Path):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://host/Site")
    _write_web_config(parent, app_settings={"PUR": "Server=s;Database=PurDb"})
    child = _write_web_project(tmp_path / "Child", "http://host/Site/Child")
    _write_web_config(child, connection_strings={"Mine": "Server=s;Database=ChildDb"})
    source = _source_file(child / "Page.cs")

    assert _lookup(tmp_path, source, "PUR", CONNECTION_STRINGS) == ConnectionAnswer()
    assert _lookup(tmp_path, source, "PUR", APP_SETTINGS).database == "PurDb"


def test_app_settings_inherit_only_from_app_settings(tmp_path: Path):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://host/Site")
    _write_web_config(parent, connection_strings={"STC": "Server=s;Database=StcDb"})
    child = _write_web_project(tmp_path / "Child", "http://host/Site/Child")
    _write_web_config(child, app_settings={"Mine": "Server=s;Database=ChildDb"})
    source = _source_file(child / "Page.cs")

    assert _lookup(tmp_path, source, "STC", APP_SETTINGS) == ConnectionAnswer()


def test_a_project_on_a_different_port_or_host_has_no_parent_application(tmp_path: Path):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://localhost:8080/Site")
    _write_web_config(parent, connection_strings={"PUR": "Server=s;Database=PurDb"})
    other_port = _write_web_project(tmp_path / "A", "http://localhost:9090/Site/A")
    other_host = _write_web_project(tmp_path / "B", "http://example.com:8080/Site/B")
    other_scheme = _write_web_project(tmp_path / "C", "https://localhost:8080/Site/C")
    for project in (other_port, other_host, other_scheme):
        _write_web_config(project, connection_strings={"Mine": "Server=s;Database=MineDb"})
        source = _source_file(project / "Page.cs")

        assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer(), project.name


def test_the_url_comparison_ignores_case_and_a_trailing_slash_and_a_default_port(
    tmp_path: Path,
):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "HTTP://LocalHost:80/SITE/")
    _write_web_config(parent, connection_strings={"PUR": "Server=s;Database=PurDb"})
    child = _write_web_project(tmp_path / "Child", "http://localhost/site/child")
    _write_web_config(child, connection_strings={"Mine": "Server=s;Database=MineDb"})
    source = _source_file(child / "Page.cs")

    assert _lookup(tmp_path, source, "PUR").database == "PurDb"


def test_a_path_prefix_must_end_at_a_segment_boundary(tmp_path: Path):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://host/App")
    _write_web_config(parent, connection_strings={"PUR": "Server=s;Database=PurDb"})
    sibling = _write_web_project(tmp_path / "Sibling", "http://host/Application")
    _write_web_config(sibling, connection_strings={"Mine": "Server=s;Database=MineDb"})
    source = _source_file(sibling / "Page.cs")

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()


def test_a_site_root_is_the_parent_of_an_application_below_it(tmp_path: Path):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://host/")
    _write_web_config(parent, connection_strings={"PUR": "Server=s;Database=PurDb"})
    child = _write_web_project(tmp_path / "Child", "http://host/Child")
    _write_web_config(child, connection_strings={"Mine": "Server=s;Database=MineDb"})
    source = _source_file(child / "Page.cs")

    assert _lookup(tmp_path, source, "PUR").database == "PurDb"


def test_a_project_file_suffix_in_upper_case_still_makes_a_web_application(tmp_path: Path):
    """The search for the nearest project file and the search for a Parent
    Application read a project file suffix with no regard to case."""
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://host/Site")
    _write_web_config(parent, connection_strings={"PUR": "Server=s;Database=PurDb"})
    child = _write_web_project(tmp_path / "Child", "http://host/Site/Child")
    (child / "Child.csproj").rename(child / "Child.CSPROJ")
    _write_web_config(child, connection_strings={"Mine": "Server=s;Database=MineDb"})
    source = _source_file(child / "Page.cs")

    assert _lookup(tmp_path, source, "PUR").database == "PurDb"


def test_two_candidate_parents_with_the_same_path_give_no_inheritance(tmp_path: Path):
    _clone(tmp_path)
    for name, database in (("SiteA", "DbA"), ("SiteB", "DbB")):
        parent = _write_web_project(tmp_path / name, "http://host/Site")
        _write_web_config(parent, connection_strings={"PUR": f"Server=s;Database={database}"})
    child = _write_web_project(tmp_path / "Child", "http://host/Site/Child")
    _write_web_config(child, connection_strings={"Mine": "Server=s;Database=MineDb"})
    source = _source_file(child / "Page.cs")

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer(
        reason=AMBIGUOUS_PARENT_APPLICATION
    )


def test_a_scan_root_below_the_repository_root_finds_a_parent_outside_the_scan_root(
    tmp_path: Path,
):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "TTPUR", "http://localhost/TTPUR")
    _write_web_config(parent, connection_strings={"PUR": "Server=s;Database=PurDb"})
    child = _write_web_project(tmp_path / "TTPUR" / "Response", "http://localhost/TTPUR/Response")
    _write_web_config(child, connection_strings={"Mine": "Server=s;Database=MineDb"})
    source = _source_file(child / "Response.Master.cs")

    answer = _lookup(child, source, "PUR")

    assert (answer.database, answer.declared_in) == ("PurDb", "TTPUR/Web.config")


def test_a_project_with_no_iis_url_has_no_parent_application(tmp_path: Path):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://host/Site")
    _write_web_config(parent, connection_strings={"PUR": "Server=s;Database=PurDb"})
    job = _write_web_project(tmp_path / "Job")
    _write_web_config(job, connection_strings={"Mine": "Server=s;Database=MineDb"})
    source = _source_file(job / "Job.cs")

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()


def test_a_project_with_an_application_settings_file_does_not_inherit(tmp_path: Path):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://host/Site")
    _write_web_config(parent, connection_strings={"PUR": "Server=s;Database=PurDb"})
    core = _write_web_project(tmp_path / "Core", "http://host/Site/Core")
    _write_application_settings(core, connection_strings={"Main": "Server=s;Database=CoreDb"})
    source = _source_file(core / "Program.cs")

    answer = _lookup(tmp_path, source, "PUR")

    assert answer.database is None
    assert answer.reason == "connection_key_not_in_project_scope"


def test_a_class_library_file_inherits_through_the_project_beside_the_scan_root_web_config(
    tmp_path: Path,
):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "TTPUR", "http://host/TTPUR")
    _write_web_config(parent, connection_strings={"PUR": "Server=s;Database=PurDb"})
    response = _write_web_project(tmp_path / "Response", "http://host/TTPUR/Response")
    _write_web_config(response, connection_strings={"Mine": "Server=s;Database=MineDb"})
    library = _write_web_project(response / "Lib")
    page = _source_file(response / "Page.cs")
    helper = _source_file(library / "Helper.cs")

    lookup = ConnectionLookup(response)

    for source in (page, helper):
        answer = lookup.for_file(source).lookup("PUR", CONNECTION_STRINGS)
        assert (answer.database, answer.declared_in) == ("PurDb", "TTPUR/Web.config")


def test_the_view_gives_the_guess_only_when_the_own_table_and_each_inherited_table_are_empty(
    tmp_path: Path,
):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://host/Site")
    _write_web_config(parent)
    child = _write_web_project(tmp_path / "Child", "http://host/Site/Child")
    _write_web_config(child)
    source = _source_file(child / "Page.cs")

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer(database="PUR")

    _write_web_config(parent, connection_strings={"Other": "Server=s;Database=OtherDb"})

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()


def test_the_search_for_the_nearest_project_file_stops_at_the_clone_root(tmp_path: Path):
    _write_web_project(tmp_path, "http://host/Outside")
    _write_web_config(tmp_path, connection_strings={"PUR": "Server=s;Database=OutsideDb"})
    repository = _clone(tmp_path / "repo")
    source = _source_file(repository / "src" / "Order.cs")

    answer = _lookup(repository, source, "PUR")

    assert answer == ConnectionAnswer(database="PUR")


def test_a_repository_with_no_clone_root_gets_no_parent_application(tmp_path: Path):
    parent = _write_web_project(tmp_path / "Site", "http://host/Site")
    _write_web_config(parent, connection_strings={"PUR": "Server=s;Database=PurDb"})
    child = _write_web_project(tmp_path / "Child", "http://host/Site/Child")
    _write_web_config(child, connection_strings={"Mine": "Server=s;Database=MineDb"})
    source = _source_file(child / "Page.cs")

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()


def test_the_declaring_file_is_relative_to_the_clone_root_when_one_exists(tmp_path: Path):
    _clone(tmp_path)
    shop = _write_web_project(tmp_path / "Shop")
    _write_web_config(shop, connection_strings={"PUR": "Server=s;Database=PurDb"})
    scan_root = shop / "Pages"
    source = _source_file(scan_root / "Order.cs")

    assert _lookup(scan_root, source, "PUR").declared_in == "Shop/Web.config"


def test_an_application_settings_file_names_itself_relative_to_the_clone_root(
    tmp_path: Path,
):
    _clone(tmp_path)
    core = _write_web_project(tmp_path / "Core")
    _write_application_settings(core, connection_strings={"Main": "Server=s;Database=CoreDb"})
    source = _source_file(core / "Program.cs")

    assert _lookup(core, source, "Main", CONNECTION_STRINGS).declared_in == "Core/appsettings.json"


# ---------------------------------------------------------------------------
# Step 3: inheritance stops where IIS stops it (ticket 06)
# ---------------------------------------------------------------------------


def _write_raw_web_config(directory: Path, body: str) -> Path:
    """Write a Web.config with a free body, for the clear, remove, and location cases."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "Web.config"
    path.write_text(f"<configuration>{body}</configuration>", encoding="utf-8")
    return path


def _parent_and_child(tmp_path: Path, parent_body: str, child_body: str = "<appSettings/>"):
    """A parent and a child application. Give back the parent, the child, and a child source.

    The child always has its own Web.config. Without one, the child would use
    the Web.config of the scan root, which is the parent one here.
    """
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://localhost/Site")
    _write_raw_web_config(parent, parent_body)
    child = _write_web_project(tmp_path / "Site" / "Response", "http://localhost/Site/Response")
    _write_raw_web_config(child, child_body)
    return parent, child, _source_file(child / "Response.Master.cs")


PARENT_PUR = (
    "<connectionStrings>"
    '<add name="PUR" connectionString="Server=sql01;Database=PurDb"/>'
    '<add name="ATV" connectionString="Server=sql01;Database=AtvDb"/>'
    "</connectionStrings>"
)


def test_a_clear_in_the_child_section_stops_all_inheritance_of_that_namespace(
    tmp_path: Path,
):
    _, _, source = _parent_and_child(
        tmp_path, PARENT_PUR, "<connectionStrings><clear/></connectionStrings>"
    )

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()
    assert _lookup(tmp_path, source, "ATV") == ConnectionAnswer()


def test_a_clear_keeps_the_entries_that_the_child_adds_after_it(tmp_path: Path):
    _, _, source = _parent_and_child(
        tmp_path,
        PARENT_PUR,
        "<connectionStrings><clear/>"
        '<add name="Own" connectionString="Server=sql02;Database=OwnDb"/>'
        "</connectionStrings>",
    )

    assert _lookup(tmp_path, source, "Own").database == "OwnDb"
    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()


def test_a_clear_stops_the_chain_above_the_child_and_not_below_it(tmp_path: Path):
    _clone(tmp_path)
    grandparent = _write_web_project(tmp_path / "Root", "http://localhost/Root")
    _write_raw_web_config(grandparent, PARENT_PUR)
    parent = _write_web_project(tmp_path / "Root" / "Mid", "http://localhost/Root/Mid")
    _write_raw_web_config(
        parent,
        "<connectionStrings><clear/>"
        '<add name="Mid" connectionString="Server=sql01;Database=MidDb"/>'
        "</connectionStrings>",
    )
    child = _write_web_project(tmp_path / "Root" / "Mid" / "Leaf", "http://localhost/Root/Mid/Leaf")
    _write_raw_web_config(child, "<appSettings/>")
    source = _source_file(child / "Leaf.cs")

    assert _lookup(tmp_path, source, "Mid").declared_in == "Root/Mid/Web.config"
    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()


def test_a_clear_in_one_namespace_leaves_the_other_namespace_inherited(tmp_path: Path):
    _, _, source = _parent_and_child(
        tmp_path,
        PARENT_PUR
        + '<appSettings><add key="PUR" value="Server=sql01;Database=PurSettingDb"/></appSettings>',
        "<connectionStrings><clear/></connectionStrings>",
    )

    assert _lookup(tmp_path, source, "PUR", APP_SETTINGS).database == "PurSettingDb"
    assert _lookup(tmp_path, source, "PUR", CONNECTION_STRINGS) == ConnectionAnswer()


def test_a_clear_in_app_settings_stops_the_inheritance_of_app_settings(tmp_path: Path):
    _, _, source = _parent_and_child(
        tmp_path,
        '<appSettings><add key="K" value="Server=sql01;Database=KDb"/></appSettings>',
        "<appSettings><clear/></appSettings>",
    )

    assert _lookup(tmp_path, source, "K", APP_SETTINGS) == ConnectionAnswer()


def test_a_remove_in_the_child_section_stops_the_inheritance_of_that_one_key(
    tmp_path: Path,
):
    _, _, source = _parent_and_child(
        tmp_path,
        PARENT_PUR,
        '<connectionStrings><remove name="PUR"/></connectionStrings>',
    )

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()
    assert _lookup(tmp_path, source, "ATV").database == "AtvDb"


def test_a_remove_in_app_settings_uses_the_key_attribute(tmp_path: Path):
    _, _, source = _parent_and_child(
        tmp_path,
        '<appSettings><add key="K" value="Server=sql01;Database=KDb"/>'
        '<add key="L" value="Server=sql01;Database=LDb"/></appSettings>',
        '<appSettings><remove key="K"/></appSettings>',
    )

    assert _lookup(tmp_path, source, "K", APP_SETTINGS) == ConnectionAnswer()
    assert _lookup(tmp_path, source, "L", APP_SETTINGS).database == "LDb"


def test_a_remove_matches_the_key_with_no_regard_to_case(tmp_path: Path):
    _, _, source = _parent_and_child(
        tmp_path,
        PARENT_PUR,
        '<connectionStrings><remove name="pur"/></connectionStrings>',
    )

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()


def test_a_remove_of_a_key_that_the_same_file_adds_later_keeps_the_later_entry(
    tmp_path: Path,
):
    _, _, source = _parent_and_child(
        tmp_path,
        PARENT_PUR,
        '<connectionStrings><remove name="PUR"/>'
        '<add name="PUR" connectionString="Server=sql02;Database=NewPurDb"/>'
        "</connectionStrings>",
    )

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer(
        database="NewPurDb", server="sql02", declared_in="Site/Response/Web.config"
    )


def test_a_remove_of_a_key_that_the_same_file_added_earlier_removes_both(tmp_path: Path):
    _, _, source = _parent_and_child(
        tmp_path,
        PARENT_PUR,
        '<connectionStrings><add name="PUR" connectionString="Server=sql02;Database=NewPurDb"/>'
        '<remove name="PUR"/></connectionStrings>',
    )

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()


def test_a_child_section_with_only_a_clear_gives_no_guess_while_a_parent_declares_entries(
    tmp_path: Path,
):
    _, _, source = _parent_and_child(
        tmp_path, PARENT_PUR, "<connectionStrings><clear/></connectionStrings>"
    )

    assert _lookup(tmp_path, source, "Unknown") == ConnectionAnswer()


def test_a_parent_section_in_a_location_that_blocks_child_applications_does_not_reach_them(
    tmp_path: Path,
):
    _, _, source = _parent_and_child(
        tmp_path,
        '<location path="." inheritInChildApplications="false">'
        f"{PARENT_PUR}</location>"
        "<connectionStrings>"
        '<add name="Shared" connectionString="Server=sql01;Database=SharedDb"/>'
        "</connectionStrings>",
    )

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()
    assert _lookup(tmp_path, source, "Shared").database == "SharedDb"


def test_a_section_in_a_location_that_blocks_child_applications_still_serves_its_own_application(
    tmp_path: Path,
):
    parent, _, _ = _parent_and_child(
        tmp_path,
        '<location path="." inheritInChildApplications="false">'
        f"{PARENT_PUR}</location>",
    )
    source = _source_file(parent / "Default.cs")

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer(
        database="PurDb", server="sql01", declared_in="Site/Web.config"
    )


def test_a_section_in_a_location_that_allows_child_applications_is_inherited(
    tmp_path: Path,
):
    _, _, source = _parent_and_child(
        tmp_path,
        '<location path="." inheritInChildApplications="true">'
        f"{PARENT_PUR}</location>",
    )

    assert _lookup(tmp_path, source, "PUR").database == "PurDb"


def test_a_section_in_a_location_for_another_path_is_not_read(tmp_path: Path):
    parent, _, _ = _parent_and_child(
        tmp_path, f'<location path="Admin">{PARENT_PUR}</location>'
    )
    source = _source_file(parent / "Default.cs")

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer(database="PUR")


def test_a_location_section_before_a_clear_of_the_same_file_is_cleared(tmp_path: Path):
    _, _, source = _parent_and_child(
        tmp_path,
        f'<location path=".">{PARENT_PUR}</location>'
        "<connectionStrings><clear/>"
        '<add name="Kept" connectionString="Server=sql01;Database=KeptDb"/>'
        "</connectionStrings>",
    )

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()
    assert _lookup(tmp_path, source, "Kept").database == "KeptDb"


def test_a_location_section_after_a_clear_of_the_same_file_survives(tmp_path: Path):
    _, _, source = _parent_and_child(
        tmp_path,
        "<connectionStrings><clear/></connectionStrings>"
        f'<location path=".">{PARENT_PUR}</location>',
    )

    assert _lookup(tmp_path, source, "PUR").database == "PurDb"


def test_a_remove_in_an_ancestor_stops_the_key_of_the_layers_above_it(tmp_path: Path):
    _clone(tmp_path)
    grandparent = _write_web_project(tmp_path / "Root", "http://localhost/Root")
    _write_raw_web_config(grandparent, PARENT_PUR)
    parent = _write_web_project(tmp_path / "Root" / "Mid", "http://localhost/Root/Mid")
    _write_raw_web_config(parent, '<connectionStrings><remove name="PUR"/></connectionStrings>')
    child = _write_web_project(tmp_path / "Root" / "Mid" / "Leaf", "http://localhost/Root/Mid/Leaf")
    _write_raw_web_config(child, "<appSettings/>")
    source = _source_file(child / "Leaf.cs")

    assert _lookup(tmp_path, source, "PUR") == ConnectionAnswer()
    assert _lookup(tmp_path, source, "ATV").declared_in == "Root/Web.config"


# ---------------------------------------------------------------------------
# Ticket 07: an ambiguous Parent Application gives a visible reason
# ---------------------------------------------------------------------------


def test_two_projects_with_the_same_iis_url_give_no_parent_application_to_each_other(
    tmp_path: Path,
):
    _clone(tmp_path)
    root = _write_web_project(tmp_path / "Site", "http://host/Site")
    _write_web_config(root, connection_strings={"PUR": "Server=s;Database=PurDb"})
    for name in ("TwinA", "TwinB"):
        twin = _write_web_project(tmp_path / name, "http://host/Site/App")
        _write_web_config(twin, connection_strings={"Mine": "Server=s;Database=MineDb"})

    answer = _lookup(tmp_path, _source_file(tmp_path / "TwinA" / "Page.cs"), "PUR")

    assert answer == ConnectionAnswer(reason=AMBIGUOUS_PARENT_APPLICATION)


def test_the_own_declaration_of_an_ambiguous_application_answers_with_no_reason(
    tmp_path: Path,
):
    _clone(tmp_path)
    for name in ("SiteA", "SiteB"):
        _write_web_project(tmp_path / name, "http://host/Site")
    child = _write_web_project(tmp_path / "Child", "http://host/Site/Child")
    _write_web_config(child, connection_strings={"Mine": "Server=s;Database=MineDb"})

    answer = _lookup(tmp_path, _source_file(child / "Page.cs"), "Mine")

    assert (answer.database, answer.reason) == ("MineDb", "")


def test_an_ambiguous_grandparent_gives_the_reason_for_a_key_that_no_nearer_ancestor_declares(
    tmp_path: Path,
):
    _clone(tmp_path)
    for name in ("RootA", "RootB"):
        root = _write_web_project(tmp_path / name, "http://host/Root")
        _write_web_config(root, connection_strings={"PUR": "Server=s;Database=PurDb"})
    parent = _write_web_project(tmp_path / "Mid", "http://host/Root/Mid")
    _write_web_config(parent, connection_strings={"ATV": "Server=s;Database=AtvDb"})
    child = _write_web_project(tmp_path / "Leaf", "http://host/Root/Mid/Leaf")
    _write_web_config(child, connection_strings={"Mine": "Server=s;Database=MineDb"})
    source = _source_file(child / "Page.cs")

    assert _lookup(tmp_path, source, "PUR").reason == AMBIGUOUS_PARENT_APPLICATION
    assert _lookup(tmp_path, source, "ATV").database == "AtvDb"
    assert _lookup(tmp_path, source, "ATV").reason == ""


def test_an_ambiguous_parent_application_gives_the_reason_in_the_app_settings_namespace_too(
    tmp_path: Path,
):
    _clone(tmp_path)
    for name in ("SiteA", "SiteB"):
        parent = _write_web_project(tmp_path / name, "http://host/Site")
        _write_web_config(parent, app_settings={"Db": "PurDb"})
    child = _write_web_project(tmp_path / "Child", "http://host/Site/Child")
    _write_web_config(child, app_settings={"Mine": "MineDb"})

    answer = _lookup(tmp_path, _source_file(child / "Page.cs"), "Db", APP_SETTINGS)

    assert answer.reason == AMBIGUOUS_PARENT_APPLICATION


def test_an_ambiguous_parent_application_keeps_the_key_as_name_guess_with_the_reason(
    tmp_path: Path,
):
    _clone(tmp_path)
    for name in ("SiteA", "SiteB"):
        _write_web_project(tmp_path / name, "http://host/Site")
    child = _write_web_project(tmp_path / "Child", "http://host/Site/Child")
    _write_web_config(child)

    answer = _lookup(tmp_path, _source_file(child / "Page.cs"), "PUR")

    assert answer == ConnectionAnswer(database="PUR", reason=AMBIGUOUS_PARENT_APPLICATION)


def test_a_failed_lookup_with_no_ambiguity_stays_silent(tmp_path: Path):
    _clone(tmp_path)
    parent = _write_web_project(tmp_path / "Site", "http://host/Site")
    _write_web_config(parent, connection_strings={"PUR": "Server=s;Database=PurDb"})
    child = _write_web_project(tmp_path / "Child", "http://host/Site/Child")
    _write_web_config(child, connection_strings={"Mine": "Server=s;Database=MineDb"})

    assert _lookup(tmp_path, _source_file(child / "Page.cs"), "Nowhere") == ConnectionAnswer()


def test_a_remove_before_the_ambiguous_link_gives_the_guess_and_no_reason(tmp_path: Path):
    _clone(tmp_path)
    for name in ("RootA", "RootB"):
        root = _write_web_project(tmp_path / name, "http://host/Root")
        _write_web_config(root, connection_strings={"PUR": "Server=s;Database=PurDb"})
    child = _write_web_project(tmp_path / "Child", "http://host/Root/Child")
    _write_raw_web_config(child, '<connectionStrings><remove name="PUR"/></connectionStrings>')

    # A file with only a `<remove>` gives the guess, as ticket 06 decided.
    answer = _lookup(tmp_path, _source_file(child / "Page.cs"), "PUR")

    assert answer == ConnectionAnswer(database="PUR")


def test_a_clear_before_the_ambiguous_link_gives_no_reason(tmp_path: Path):
    _clone(tmp_path)
    for name in ("RootA", "RootB"):
        root = _write_web_project(tmp_path / name, "http://host/Root")
        _write_web_config(root, connection_strings={"PUR": "Server=s;Database=PurDb"})
    child = _write_web_project(tmp_path / "Child", "http://host/Root/Child")
    _write_raw_web_config(
        child,
        '<connectionStrings><clear/><add name="Mine" connectionString="Server=s;Database=MineDb"/>'
        "</connectionStrings>",
    )

    assert _lookup(tmp_path, _source_file(child / "Page.cs"), "PUR") == ConnectionAnswer()
