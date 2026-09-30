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
