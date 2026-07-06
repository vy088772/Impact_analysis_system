# service/api.py
"""
影響分析 HTTP 服務（FastAPI，無 AI）。

啟動：
    python -m service.api
    # 或
    uvicorn service.api:app --host 127.0.0.1 --port 8800

端點：
    GET  /health   → {"status": "ok"}
    POST /analyze  → AnalyzeResponse（依 program_names 回傳靜態分析結果）
    POST /refresh  → RefreshResponse（git pull + 重新解析，覆寫快取）
    POST /refresh_sql → RefreshSqlResponse（重新連線 SQL Server 撈取 SP/View/
                        Function/資料表 Schema，覆寫本機 SQL 快取）
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from config.settings import settings
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    RefreshRequest,
    RefreshResponse,
    RefreshSqlRequest,
    RefreshSqlResponse,
)
from . import analyze_service

app = FastAPI(
    title="Impact Analysis Service",
    description="程式碼/DB 靜態影響分析服務（供 spec-rag 協調呼叫，不含 AI）",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    if not req.program_names:
        raise HTTPException(status_code=400, detail="program_names 不可為空")
    try:
        return analyze_service.analyze(req)
    except ValueError as exc:
        # 來源解析 / 設定問題 → 400
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        # 其餘視為服務端錯誤 → 500
        raise HTTPException(status_code=500, detail=f"分析失敗：{exc}")


@app.post("/refresh", response_model=RefreshResponse)
def refresh(req: RefreshRequest) -> RefreshResponse:
    """更新指令：git pull 取得最新程式碼並重新解析、覆寫快取。"""
    source = {
        "project": req.source.project,
        "repo": req.source.repo,
        "branch": req.source.branch,
        "path": req.source.path,
    }
    try:
        result = analyze_service.refresh_source(source)
        return RefreshResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"更新失敗：{exc}")


@app.post("/refresh_sql", response_model=RefreshSqlResponse)
def refresh_sql(req: RefreshSqlRequest) -> RefreshSqlResponse:
    """更新 SQL 快取指令：重新連線 SQL Server 撈取整庫 SP/View/Function 定義與
    資料表 Schema，覆寫本機落地快取（data/sql_cache/）。

    server/db_name 由呼叫端（catalog）提供，缺一即報錯、不嘗試連線。"""
    if not req.database:
        raise HTTPException(status_code=400, detail="database 不可為空")
    if not req.server or not req.db_name:
        raise HTTPException(
            status_code=400,
            detail=f"server/db_name 不可為空（收到 server={req.server!r}, db_name={req.db_name!r}）；"
                   f"請在 catalog（spec-rag 端）為此系統設定完整的 database.server/database.name。",
        )
    try:
        result = analyze_service.refresh_sql_source(req.database, req.server, req.db_name, req.db_schema)
        return RefreshSqlResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"SQL 快取更新失敗：{exc}")


def main() -> None:
    import uvicorn

    uvicorn.run(
        "service.api:app",
        host=settings.SERVICE_HOST,
        port=settings.SERVICE_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
