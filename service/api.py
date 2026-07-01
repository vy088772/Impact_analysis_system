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
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from config.settings import settings
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    RefreshRequest,
    RefreshResponse,
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
