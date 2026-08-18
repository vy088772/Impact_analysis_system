"""Export the live FastAPI app's OpenAPI schema to a committed JSON file.

The schema is never hand-maintained. It is regenerated from `service.api:app`
each time this script runs, so it cannot silently drift from the real route
definitions (`/analyze`, `/refresh`, `/path_evidence`, and every other
registered endpoint).

Examples:
    python -m tools.export_openapi_schema
    python -m tools.export_openapi_schema --check
    python -m tools.export_openapi_schema --output docs/openapi/openapi.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service.api import app  # noqa: E402

DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "docs" / "openapi" / "openapi.json"


def build_schema() -> Dict[str, Any]:
    """Return the app's current OpenAPI schema as a plain dict."""
    app.openapi_schema = None  # force FastAPI to rebuild from live routes
    return app.openapi()


def render(schema: Dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"目標檔案路徑（預設：{DEFAULT_OUTPUT_PATH.relative_to(PROJECT_ROOT)}）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只比對現有檔案與即時 schema 是否一致，不寫檔（找到差異時 exit code 1）",
    )
    args = parser.parse_args(argv)

    rendered = render(build_schema())

    if args.check:
        existing = args.output.read_text(encoding="utf-8") if args.output.exists() else None
        if existing == rendered:
            print(f"OpenAPI schema 與 {args.output} 一致")
            return 0
        print(
            f"OpenAPI schema 與 {args.output} 不一致，"
            "請執行 `python -m tools.export_openapi_schema` 重新產生",
            file=sys.stderr,
        )
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"OpenAPI schema 已匯出至 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
