"""Regression guard for the committed OpenAPI export.

`docs/openapi/openapi.json` must always equal what
`tools.export_openapi_schema` regenerates from the live FastAPI app. If this
test fails, run `python -m tools.export_openapi_schema` and commit the
result.
"""

from __future__ import annotations

from tools.export_openapi_schema import DEFAULT_OUTPUT_PATH, build_schema, render


def response_schema_for(schema: dict, route: str) -> dict:
    return schema["paths"][route]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]


def response_ref_for(schema: dict, route: str) -> str:
    return response_schema_for(schema, route)["$ref"].rsplit("/", 1)[-1]


def test_committed_export_matches_live_app_schema() -> None:
    assert DEFAULT_OUTPUT_PATH.exists(), (
        f"{DEFAULT_OUTPUT_PATH} 不存在，請先執行 "
        "`python -m tools.export_openapi_schema`"
    )
    committed = DEFAULT_OUTPUT_PATH.read_text(encoding="utf-8")
    regenerated = render(build_schema())
    assert committed == regenerated


def test_export_covers_analyze_refresh_and_path_evidence() -> None:
    schema = build_schema()
    paths = schema["paths"]

    for route in ("/analyze", "/refresh", "/path_evidence"):
        assert route in paths, f"{route} missing from exported OpenAPI schema"
        assert response_schema_for(schema, route), f"{route} has no response schema"


def test_refresh_wrapper_summary_is_typed_not_a_raw_dict() -> None:
    schema = build_schema()
    refresh_response_ref = response_ref_for(schema, "/refresh")
    refresh_schema = schema["components"]["schemas"][refresh_response_ref]

    wrapper_summary_field = refresh_schema["properties"]["wrapper_summary"]
    wrapper_summary_ref = wrapper_summary_field["$ref"].rsplit("/", 1)[-1]

    # The old shape was an untyped `Dict[str, Any]`, which FastAPI renders as
    # a bare `{"type": "object"}` with no `$ref` and no named component. A
    # typed Pydantic model instead shows up as a `$ref` to a named schema
    # with declared `properties` — proving ticket 01's model, not the old
    # untyped dict, is what the live app actually serves.
    wrapper_summary_schema = schema["components"]["schemas"][wrapper_summary_ref]
    assert wrapper_summary_ref == "WrapperSummary"
    assert "properties" in wrapper_summary_schema
    assert "evidence_statuses" in wrapper_summary_schema["properties"]
    assert "totals" in wrapper_summary_schema["properties"]
