"""The short reasons of a source that the service cannot read.

The Environment Check and the `behind_source` check (Impact ADR-0045) give the same reasons for the
same failure. Thus both use this module. The web shows a reason as a lock reason or as the hover
text of a "無法檢查" row, so a reason is one short line.
"""

from __future__ import annotations

from typing import Optional

try:
    import pyodbc as _pyodbc

    _odbc_errors: tuple = (_pyodbc.Error,)
except ImportError:  # 沒有 pyodbc 的機器：沒有 ODBC 錯誤可分類
    _odbc_errors = ()


_MAX_REASON_LENGTH = 160


def short_reason(text: str) -> str:
    """原因只留第一行，最多 _MAX_REASON_LENGTH 個字：頁面把它當滑鼠提示顯示。"""
    first = (text.strip().splitlines() or [""])[0]
    return first if len(first) <= _MAX_REASON_LENGTH else first[: _MAX_REASON_LENGTH - 1] + "…"


def no_answer(what: str, seconds: float) -> str:
    """The reason of a source that gave no answer in its time limit."""
    return f"{what} 在 {seconds:g} 秒內沒有回應"


def sql_failure_reason(exc: Optional[BaseException], seconds: Optional[float] = None) -> str:
    """一個 SQL Server 連線錯誤的簡短原因。

    seconds：登入時間限制，用在逾時的原因；None 表示不寫秒數。"""
    if exc is None:
        return "SQL Server 連線失敗"
    if isinstance(exc, _odbc_errors):
        state = str(exc.args[0]) if exc.args else ""
        if state == "HYT00":
            return "SQL Server 沒有回應" if seconds is None else no_answer("SQL Server", seconds)
        if state in ("08001", "08S01"):
            return "連不到 SQL Server（主機名稱錯誤、網路不通，或伺服器沒有回應）"
        if state == "28000":
            return "SQL Server 拒絕這個登入帳號"
        # Windows says IM002; unixODBC says 01000 "Can't open lib".
        if state == "IM002" or "Can't open lib" in str(exc):
            return "這台機器沒有 SQL Server 的 ODBC 驅動程式"
        return f"SQL Server 連線失敗（{state or type(exc).__name__}）"
    return short_reason(f"SQL Server 連線失敗：{exc}")
