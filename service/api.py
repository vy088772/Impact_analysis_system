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
    POST /refresh  → RefreshJobResponse（提交 Refresh Job：git pull + 重新解析，
                        覆寫快取；指定 program_names 時直接執行並回 RefreshResponse）
    POST /refresh_sql → RefreshJobResponse（提交 Refresh Job：重新連線 SQL Server
                        撈取 SP/View/Function/資料表 Schema，建立 AST SQL Execution
                        Graph，覆寫本機 SQL 快取）
    POST /refresh_jobs → RefreshJobResponse（提交一個 Refresh Job，排入 Refresh Queue）
    GET  /refresh_jobs/{job_id} → RefreshJobResponse（狀態、排隊位置、進度、結果）
    POST /refresh_jobs/{job_id}/cancel → RefreshJobResponse（取消 waiting 的 job）
    POST /wrapper_contracts/accept → WrapperContractAcceptanceResponse（reviewed
                         proposal 的 preview 或明確 apply）
    POST /find_by_sp  → FindBySPResponse（反查哪些程式呼叫了指定 SP，純比對已
                        快取的掃描結果；cache_only=True 時不觸發 clone）
    POST /find_by_table → FindByTableResponse（反查哪些程式存取了指定資料表，
                        純比對已快取的掃描結果；cache_only=True 時不觸發 clone）
    POST /locate_object → LocateObjectResponse（從 Object Location Index 猜哪些
                        Database 可能持有指定物件名稱，完全不開任何 SQL 快取；
                        供 /find_by_sp、/find_by_table 的呼叫端先縮小範圍）
    POST /flow_chain  → FlowChainResponse（組出變更影響「關係鏈」候選清單，純靜態
                        組裝、無 AI 判斷；forward：錨點方法→呼叫鏈→SP→SP→資料表；
                        backward：資料表（可選欄位）→SP→C#方法→UI控制項事件；
                        cache_only=True 時不觸發 clone）
    POST /path_evidence → PathEvidenceResponse（依 path_id 還原單一路徑的 C#、SQL
                         definition 與 terminal operation evidence）
    GET  /scan_records → ScanRecordListResponse（唯讀列出磁碟上每一份 SQL 快取
                        的 server/database/schema 與 Scan Record 掃描時間；不
                        連線、不觸發掃描、不讀 Database Registry）
"""
from __future__ import annotations

from typing import Callable, Union

from fastapi import FastAPI, HTTPException

from config.settings import settings
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    RefreshRequest,
    RefreshResponse,
    WrapperContractAcceptanceRequest,
    WrapperContractAcceptanceResponse,
    RefreshSqlRequest,
    RefreshSqlResponse,
    RefreshJobRequest,
    RefreshJobResponse,
    FindBySPRequest,
    FindBySPResponse,
    FindByTableRequest,
    FindByTableResponse,
    LocateObjectRequest,
    LocateObjectResponse,
    FlowChainRequest,
    FlowChainResponse,
    PathEvidenceRequest,
    PathEvidenceResponse,
    ScanRecordEntry,
    ScanRecordListResponse,
)
from . import analyze_service, contract_acceptance, refresh_progress, refresh_queue, sql_cache_store
from .repo_manager import peek_scan_roots

app = FastAPI(
    title="Impact Analysis Service",
    description="程式碼/DB 靜態影響分析服務（供 spec-rag 協調呼叫，不含 AI）",
    version="1.0.0",
)


def _graph_readiness_http_error(exc: analyze_service.SqlExecutionGraphRequiredError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "database": exc.database,
            "reason": exc.reason,
            "rebuild_action": exc.rebuild_action,
            "message": str(exc),
        },
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
    except analyze_service.SqlExecutionGraphRequiredError as exc:
        raise _graph_readiness_http_error(exc) from exc
    except ValueError as exc:
        # 來源解析 / 設定問題 → 400
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        # 其餘視為服務端錯誤 → 500
        raise HTTPException(status_code=500, detail=f"分析失敗：{exc}")


def _source_dict(req: RefreshRequest) -> dict:
    return {
        "project": req.source.project,
        "repo": req.source.repo,
        "branch": req.source.branch,
        "path": req.source.path,
    }


def _csharp_refresh_run(req: RefreshRequest) -> Callable[[Callable[..., None]], dict]:
    """The rebuild of one C# Scan Result. The queue calls it; a program-scoped refresh calls it directly."""
    source = _source_dict(req)

    def run(_report: Callable[..., None]) -> dict:
        refresh_kwargs = {"program_names": req.program_names}
        selector = req.wrapper_contract
        selector_is_set = (
            bool(selector)
            if not isinstance(selector, str)
            else bool(selector.strip())
        )
        if selector_is_set:
            refresh_kwargs["wrapper_contract"] = req.wrapper_contract
        if req.system.strip():
            refresh_kwargs["database"] = req.system.strip()
        if req.rerun_decompile_receiver_types:
            refresh_kwargs["rerun_receiver_types"] = req.rerun_decompile_receiver_types
        result = analyze_service.refresh_source(source, **refresh_kwargs)
        return RefreshResponse(**result).model_dump()

    return run


def _csharp_cache_key(req: RefreshRequest) -> str:
    """The scan roots name the cache. Reads the paths only: it never clones or pulls."""
    return refresh_queue.csharp_key(str(root) for root in peek_scan_roots(_source_dict(req)))


def _submit_csharp_job(req: RefreshRequest) -> RefreshJobResponse:
    snapshot = refresh_queue.shared_queue.submit(
        key=_csharp_cache_key(req),
        kind="csharp",
        database=req.system.strip() or req.source.repo,
        run=_csharp_refresh_run(req),
    )
    return RefreshJobResponse(**snapshot)


@app.post("/refresh", response_model=Union[RefreshJobResponse, RefreshResponse])
def refresh(req: RefreshRequest) -> Union[RefreshJobResponse, RefreshResponse]:
    """更新指令。完整 refresh 提交一個 Refresh Job 並回傳該 job（Refresh Queue 一次只跑一個）。

    指定 program_names 的 refresh 仍是直接指令，不進 Refresh Queue，直接回傳結果。"""
    if not req.program_names:
        return _submit_csharp_job(req)
    try:
        return RefreshResponse(**_csharp_refresh_run(req)(lambda *args: None))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"更新失敗：{exc}")


@app.post(
    "/wrapper_contracts/accept",
    response_model=WrapperContractAcceptanceResponse,
)
def accept_wrapper_contract(
    req: WrapperContractAcceptanceRequest,
) -> WrapperContractAcceptanceResponse:
    """Preview or explicitly apply one reviewed external-wrapper proposal."""
    operation = req.operation.strip().casefold() or "preview"
    if operation not in {"preview", "apply"}:
        raise HTTPException(status_code=400, detail="operation 必須是 preview 或 apply")
    if req.apply and operation != "apply":
        raise HTTPException(
            status_code=400,
            detail="apply=true 必須搭配 operation=apply",
        )
    apply = operation == "apply"
    kwargs = {
        "system_id": req.system_id,
        "requested_selector": req.requested_selector,
        "scan_roots": req.scan_roots,
        "apply": apply,
    }
    try:
        result = contract_acceptance.accept_external_wrapper_contract(
            req.proposal,
            **kwargs,
        )
        return WrapperContractAcceptanceResponse(**result)
    except contract_acceptance.ContractAcceptanceError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc), "details": list(exc.details)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"contract acceptance 失敗：{exc}") from exc


_LOOKUP_CONFLICT_ERRORS = (
    analyze_service.SqlExecutionGraphRequiredError,
    analyze_service.AmbiguousDatabaseError,
)


def _lookup_conflict_http_error(
    exc: Union[analyze_service.SqlExecutionGraphRequiredError, analyze_service.AmbiguousDatabaseError],
) -> HTTPException:
    """The 409 of a reverse lookup: the Database is not scanned, or it lives on several hosts."""
    if isinstance(exc, analyze_service.SqlExecutionGraphRequiredError):
        return _graph_readiness_http_error(exc)
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "database": exc.database,
            "servers": exc.servers,
            "message": str(exc),
        },
    )


@app.post("/find_by_sp", response_model=FindBySPResponse)
def find_by_sp(req: FindBySPRequest) -> FindBySPResponse:
    """反查「哪些程式呼叫了這支 SP」（純快取比對；cache_only=True 時不觸發 clone）。"""
    if not req.sp_name.strip():
        raise HTTPException(status_code=400, detail="sp_name 不可為空")
    try:
        return analyze_service.find_by_sp(req)
    except _LOOKUP_CONFLICT_ERRORS as exc:
        raise _lookup_conflict_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"SP 反查失敗：{exc}")


@app.post("/find_by_table", response_model=FindByTableResponse, response_model_exclude_none=True)
def find_by_table(req: FindByTableRequest) -> FindByTableResponse:
    """反查「哪些程式存取了這張資料表」（純快取比對；cache_only=True 時不觸發 clone）。"""
    if not req.table_name.strip():
        raise HTTPException(status_code=400, detail="table_name 不可為空")
    try:
        return analyze_service.find_by_table(req)
    except _LOOKUP_CONFLICT_ERRORS as exc:
        raise _lookup_conflict_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"資料表反查失敗：{exc}")


@app.post("/locate_object", response_model=LocateObjectResponse, response_model_exclude_none=True)
def locate_object(req: LocateObjectRequest) -> LocateObjectResponse:
    """從 Object Location Index 猜哪些 Database 可能持有指定物件名稱，不開任何 SQL 快取。"""
    try:
        return analyze_service.locate_object(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"物件定位失敗：{exc}")


@app.post("/flow_chain", response_model=FlowChainResponse)
def flow_chain(req: FlowChainRequest) -> FlowChainResponse:
    """組出變更影響「關係鏈」候選清單（純靜態組裝，無 AI 判斷；cache_only=True 時不觸發 clone）。

    direction="forward" 時 program_name/anchor_method 必填；
    direction="backward" 時 table_name 必填（column_name 選填，僅近似文字比對）。
    """
    if req.direction not in ("forward", "backward"):
        raise HTTPException(status_code=400, detail="direction 必須是 forward 或 backward")
    if req.direction == "forward" and (not req.program_name.strip() or not req.anchor_method.strip()):
        raise HTTPException(status_code=400, detail="direction=forward 時 program_name/anchor_method 不可為空")
    if req.direction == "backward" and not req.table_name.strip():
        raise HTTPException(status_code=400, detail="direction=backward 時 table_name 不可為空")
    try:
        return analyze_service.flow_chain(req)
    except analyze_service.SqlExecutionGraphRequiredError as exc:
        raise _graph_readiness_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"關係鏈組裝失敗：{exc}")


@app.post("/path_evidence", response_model=PathEvidenceResponse)
def path_evidence(req: PathEvidenceRequest) -> PathEvidenceResponse:
    """依 path_id 取得目前 source/SQL snapshot 對應的精確 evidence。"""
    if not req.path_id.strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_path_id", "message": "path_id 不可為空"},
        )
    try:
        return analyze_service.get_path_evidence(req)
    except analyze_service.SqlExecutionGraphRequiredError as exc:
        raise _graph_readiness_http_error(exc) from exc
    except analyze_service.PathEvidenceError as exc:
        status_code = 404 if exc.code == "path_not_found" else 409
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Path evidence 取得失敗：{exc}") from exc


def _submit_sql_job(req: RefreshSqlRequest) -> RefreshJobResponse:
    if not req.database:
        raise HTTPException(status_code=400, detail="database 不可為空")
    if not req.server or not req.db_name:
        raise HTTPException(
            status_code=400,
            detail=f"server/db_name 不可為空（收到 server={req.server!r}, db_name={req.db_name!r}）；"
                   f"請在 catalog（spec-rag 端）為此系統設定完整的 database.server/database.name。",
        )
    try:
        key = refresh_queue.sql_key(sql_cache_store.CacheIdentity.of(req.server, req.db_name).key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def run(report: Callable[..., None]) -> dict:
        return analyze_service.refresh_sql_source(
            req.database,
            req.server,
            req.db_name,
            user_id=req.db_user_id,
            password=req.db_password,
            progress_callback=report,
        )

    snapshot = refresh_queue.shared_queue.submit(
        key=key, kind="sql", database=req.database, run=run, job_id=req.job_id
    )
    return RefreshJobResponse(**snapshot)


@app.post("/refresh_sql", response_model=RefreshJobResponse)
def refresh_sql(req: RefreshSqlRequest) -> RefreshJobResponse:
    """更新 SQL 快取指令：提交一個 Refresh Job 並回傳該 job；不在請求內做事。

    Refresh Queue 一次只跑一個 job：重新連線 SQL Server 撈取整庫 SP/View/Function 定義與
    資料表 Schema，使用 ScriptDom 建立 SQL Execution Graph，覆寫本機落地快取
    （data/sql_cache/）。同一份快取已有 waiting／running 的 job 時，回傳那個既有 job。

    server/db_name 由呼叫端（catalog）提供，缺一即報錯、不排入佇列。連線身分預設
    用 .env 的全域 DB_AUTH_MODE；請求帶了完整的 db_user_id/db_password 才改用那組
    覆寫（ADR-0010）。"""
    return _submit_sql_job(req)


@app.post("/refresh_jobs", response_model=RefreshJobResponse)
def submit_refresh_job(req: RefreshJobRequest) -> RefreshJobResponse:
    """提交一個 Refresh Job：重建一份 SQL 快取，或一份 C# Scan Result。"""
    if req.kind == "sql":
        if req.sql is None:
            raise HTTPException(status_code=400, detail="kind=sql 需要 sql 欄位")
        return _submit_sql_job(req.sql)
    if req.csharp is None:
        raise HTTPException(status_code=400, detail="kind=csharp 需要 csharp 欄位")
    if req.csharp.program_names:
        raise HTTPException(
            status_code=400,
            detail="指定 program 的 refresh 是直接指令，不進 Refresh Queue",
        )
    return _submit_csharp_job(req.csharp)


@app.get("/refresh_jobs/{job_id}", response_model=RefreshJobResponse)
def read_refresh_job(job_id: str) -> RefreshJobResponse:
    """讀取一個 Refresh Job：狀態、排隊位置、進度與結果。"""
    snapshot = refresh_queue.shared_queue.get(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="找不到這個 refresh job")
    return RefreshJobResponse(**snapshot)


@app.post("/refresh_jobs/{job_id}/cancel", response_model=RefreshJobResponse)
def cancel_refresh_job(job_id: str) -> RefreshJobResponse:
    """取消一個 waiting 的 Refresh Job。running 的 job 不可取消：停止可能留下寫到一半的快取。"""
    outcome = refresh_queue.shared_queue.cancel(job_id)
    if outcome == refresh_queue.NOT_FOUND:
        raise HTTPException(status_code=404, detail="找不到這個 refresh job")
    if outcome == refresh_queue.RUNNING:
        raise HTTPException(status_code=409, detail="job 正在執行，無法取消")
    if outcome == refresh_queue.FINISHED:
        raise HTTPException(status_code=409, detail="job 已結束，無法取消")
    return read_refresh_job(job_id)


@app.get("/scan_records", response_model=ScanRecordListResponse)
def scan_records() -> ScanRecordListResponse:
    """唯讀列出磁碟上每一份 SQL 快取的身分與 Scan Record（掃描時間）。

    純目錄列舉（sql_cache_store.list_caches()）：不連線 SQL Server、不觸發
    掃描、不修改任何快取，也不讀 llamaindex-spec-rag 的 Database Registry——
    兩者本來就是分開記錄的兩件事（intent vs. fact），這個端點只讀 fact。
    """
    return ScanRecordListResponse(
        records=[
            ScanRecordEntry(
                server=row.server,
                database=row.database,
                scanned_at=row.scanned_at,
            )
            for row in sql_cache_store.list_caches()
        ]
    )


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
