"""A real Analyze HTTP response backed by controlled scan and cache inputs."""

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from service import analyze_service, sp_fetcher
from service.api import app
from tests.program_screen_fixtures import _scan
from tests.request_context_fixtures import RequestStores
from tests.sql_cache_fixtures import orders_db_sql_graph


def actual_http_json() -> str:
    with TemporaryDirectory() as directory, MonkeyPatch.context() as monkeypatch:
        root = Path(directory)
        scan = _scan(
            root,
            pages=["OrderPage.aspx"],
            controllers={"OrderPage.aspx.cs": ["SaveData"]},
            invocations={"OrderPage.aspx.cs": [{
                "class_name": "OrderPage",
                "method_name": "SaveData",
                "command_text_kind": "literal",
                "command_text": "dbo.usp_SaveOrder",
                "command_type_stored_procedure": True,
                "terminal_sink": "ExecuteNonQuery",
                "connection_expression": "conn",
                "start_offset": 0,
                "end_offset": 10,
            }]},
        )
        scan.connection_sources[str((root / "OrderPage.aspx.cs").resolve())] = {
            "conn": {"server": "vmsystest07", "database": "OrdersDb", "declared_in": "Web.config"}
        }
        stores = RequestStores.of(root, scan)
        stores.install_analyze(monkeypatch)
        cache = orders_db_sql_graph()
        cache["procedures"][0].update(
            definition="UPDATE dbo.SOrder SET Status = 1", parameters=["@Id int"]
        )
        monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda identity: cache)
        monkeypatch.setattr(sp_fetcher, "load_cached", lambda identity: cache)
        with TestClient(app) as client:
            response = client.post("/analyze", json={
                "program_names": ["OrderPage", "Missing"],
                "database": "OrdersDb",
                "include_snippets": True,
                "include_sp_defs": True,
                "include_view_layer": True,
            })
        assert response.status_code == 200, response.text
        return response.text


if __name__ == "__main__":
    print("ANALYZE_JSON:" + actual_http_json())