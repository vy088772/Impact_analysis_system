"""The Environment Check of the Impact service: can this process reach SQL Server and Azure Repos?

The web asks for it when it starts and when the maintainer asks to check again
(`llamaindex-spec-rag` ADR-0020: each Update Capability is tested in the process that makes the
connection). The check logs in to each server of the Database Registry (the servers that the
catalog names) with a short login time limit, and runs `git ls-remote` one time for each remote
host, against the first repository of that host. A remote host is one Azure DevOps project:
`dev.azure.com/<org>/<project>`.

The service keeps the last result in memory. A SQL row of a failed server and a C# row of a failed
host get that failure as their lock reason: the service refuses their Refresh Jobs, and "update all"
skips them. Before the first check, and after a restart, nothing is locked.

Each probe returns None when it passes, or a plain reason when it fails. Tests replace the probes.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Optional

from config.settings import settings

from . import source_check, sql_cache_store

SQL_LOGIN_TIMEOUT_SECONDS = 5
GIT_TIMEOUT_SECONDS = 15
# A probe that runs past its limit plus this margin fails, even when its own time limit did not work.
_MARGIN_SECONDS = 3


def _no_answer(what: str, seconds: float) -> str:
    return f"{what} 在 {seconds:g} 秒內沒有回應"


def probe_sql_server(server: str, database: str, user_id: str, password: str) -> Optional[str]:
    """Log in to `server` (into `database`) with a short login time limit."""
    try:
        import pyodbc
    except ImportError:
        return "這台機器沒有 pyodbc，不能連線 SQL Server"
    try:
        config = settings.build_database_config(
            alias=server, server=server, database_name=database, user_id=user_id, password=password
        )
        config.timeout = SQL_LOGIN_TIMEOUT_SECONDS
        connection = pyodbc.connect(config.get_connection_string(), timeout=SQL_LOGIN_TIMEOUT_SECONDS)
    except pyodbc.Error as exc:
        state = str(exc.args[0]) if exc.args else ""
        if state in ("HYT00", "08001", "08S01"):
            return _no_answer("SQL Server", SQL_LOGIN_TIMEOUT_SECONDS)
        if state == "28000":
            return "SQL Server 拒絕這個登入帳號"
        # Windows says IM002; unixODBC says 01000 "Can't open lib".
        if state == "IM002" or "Can't open lib" in str(exc):
            return "這台機器沒有 SQL Server 的 ODBC 驅動程式"
        return f"SQL Server 連線失敗（{state or type(exc).__name__}）"
    except Exception as exc:  # a broken configuration is a failure of this server only
        return f"SQL Server 連線失敗：{exc}"
    connection.close()
    return None


def probe_azure_repos(source: dict) -> Optional[str]:
    """Run `git ls-remote` against the repository of `source`."""
    if not source_check.can_ask_remote(source):
        return "Impact 服務沒有設定 AZURE_DEVOPS_ORG 或 AZURE_DEVOPS_PAT"
    try:
        result = source_check.ls_remote(source, timeout=GIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return _no_answer("Azure Repos", GIT_TIMEOUT_SECONDS)
    except FileNotFoundError:
        return "這台機器沒有 git"
    if result.returncode != 0:
        lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
        detail = (lines[-1] if lines else f"exit {result.returncode}").replace(settings.AZURE_DEVOPS_PAT or "\0", "***")
        return f"git ls-remote 失敗：{detail}"
    return None


def remote_host(source: dict) -> str:
    """The remote host of a catalog source: its Azure DevOps project."""
    return f"dev.azure.com/{settings.AZURE_DEVOPS_ORG}/{str(source.get('project') or '').strip()}"


@dataclass
class LastCheck:
    """The last result, and the lock reason of each failed server and host."""

    result: dict[str, Any] = field(default_factory=lambda: {"checked_at": None, "capabilities": []})
    sql_locks: dict[str, str] = field(default_factory=dict)
    host_locks: dict[str, str] = field(default_factory=dict)


_lock = threading.Lock()
_last = LastCheck()


@dataclass(frozen=True)
class _Probe:
    capability: str
    target: str
    what: str
    time_limit: float
    run: Callable[[], Optional[str]]


def _servers(catalog: Iterable[dict]) -> dict[str, tuple[str, str]]:
    """Each server of the catalog (normalized, as a SQL row shows it): the first (server, database)."""
    servers: dict[str, tuple[str, str]] = {}
    for system in catalog:
        for declared in system.get("databases") or []:
            if not isinstance(declared, dict):
                continue
            server, database = str(declared.get("server") or "").strip(), str(declared.get("name") or "").strip()
            target = sql_cache_store.normalize_server(server)
            if target and database:
                servers.setdefault(target, (server, database))
    return servers


def _hosts(catalog: Iterable[dict]) -> dict[str, dict]:
    """Each remote host of the catalog: its first repository."""
    from .cache_freshness import sources_of

    hosts: dict[str, dict] = {}
    for source in sources_of(catalog):
        hosts.setdefault(remote_host(source), source)
    return hosts


def _probes(catalog: list, sql_credentials: Mapping[str, Any]) -> list[_Probe]:
    probes = []
    for target, (server, database) in _servers(catalog).items():
        override = sql_credentials.get(target)
        user_id = getattr(override, "db_user_id", "") if override else ""
        password = getattr(override, "db_password", "") if override else ""
        probes.append(
            _Probe(
                "sql_server", target, "SQL Server", SQL_LOGIN_TIMEOUT_SECONDS,
                lambda s=server, d=database, u=user_id, p=password: probe_sql_server(s, d, u, p),
            )
        )
    for target, source in _hosts(catalog).items():
        probes.append(
            _Probe("azure_repos", target, "Azure Repos", GIT_TIMEOUT_SECONDS, lambda s=source: probe_azure_repos(s))
        )
    return probes


def _locks_of(capability: str, target: str) -> str:
    return f"{target} 的 SQL 列" if capability == "sql_server" else f"{target} 的 C# 列"


def run(catalog: list, sql_credentials: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Run every probe at the same time, keep the result and its locks, and return the result."""
    probes = _probes(catalog, sql_credentials or {})
    outcomes: dict[int, Optional[str]] = {}

    def run_one(index: int, probe: _Probe) -> None:
        try:
            outcomes[index] = probe.run()
        except Exception as exc:  # a broken probe fails its own target only
            outcomes[index] = f"{probe.what} 的測試失敗：{exc}"

    threads = [threading.Thread(target=run_one, args=item, daemon=True) for item in enumerate(probes)]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    items = []
    last = LastCheck()
    for index, (probe, thread) in enumerate(zip(probes, threads)):
        thread.join(max(0.0, started + probe.time_limit + _MARGIN_SECONDS - time.monotonic()))
        reason = _no_answer(probe.what, probe.time_limit) if thread.is_alive() else outcomes[index]
        items.append(
            {
                "capability": probe.capability,
                "target": probe.target,
                "ok": reason is None,
                "reason": reason or "",
                "locks": "" if reason is None else _locks_of(probe.capability, probe.target),
            }
        )
        if reason is not None:
            locks = last.sql_locks if probe.capability == "sql_server" else last.host_locks
            locks[probe.target] = reason
    last.result = {
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "capabilities": items,
    }
    global _last
    with _lock:
        _last = last
    return last.result


def result() -> dict[str, Any]:
    """The last result; `checked_at` is None before the first check."""
    with _lock:
        return _last.result


def sql_lock_reason(server: str) -> str:
    """The lock reason of the SQL rows of `server` (normalized), or an empty text."""
    with _lock:
        return _last.sql_locks.get(server, "")


def csharp_lock_reason(source: Optional[dict]) -> str:
    """The lock reason of the C# row of `source`, or an empty text."""
    if source is None:
        return ""
    with _lock:
        return _last.host_locks.get(remote_host(source), "")
