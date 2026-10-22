"""The Environment Check of the Impact service: can this process reach SQL Server and Azure Repos?

The web asks for it when it starts and when the maintainer asks to check again
(`llamaindex-spec-rag` ADR-0020: each Update Capability is tested in the process that makes the
connection). The check logs in to each server of the Database Registry with a short login time
limit, and runs `git ls-remote` one time for each repository of the catalog, with at most
`GIT_AT_ONCE` of them at one time. A failure of one repository locks the C# rows of that
repository only.

The service keeps the failures of the last check in memory. A SQL row of a failed server and a C#
row of a failed repository get that failure as their lock reason: the service refuses their Refresh Jobs,
and "update all" skips them. Before the first check, and after a restart, nothing is locked.

Each probe returns None when it passes, or a plain reason when it fails. Tests replace the probes.
"""

from __future__ import annotations

import math
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, List, Mapping, Optional, Tuple

from config.settings import settings

from . import source_check, sql_cache_store, system_targets
from .schemas import EnvironmentCheckResponse, SqlCredentialOverride, UpdateCapabilityResult

SQL_LOGIN_TIMEOUT_SECONDS = 5
GIT_TIMEOUT_SECONDS = 15
# 30 repositories take about 1 second at 8 at one time (measured 2026-10-22), well under the SQL limit.
GIT_AT_ONCE = 8
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
        if state == "HYT00":
            return _no_answer("SQL Server", SQL_LOGIN_TIMEOUT_SECONDS)
        if state in ("08001", "08S01"):
            return "連不到 SQL Server（主機名稱錯誤、網路不通，或伺服器沒有回應）"
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


@dataclass
class LastCheck:
    """The lock reasons of the last check: capability -> target -> reason."""

    locks: dict[str, dict[str, str]] = field(default_factory=dict)


_lock = threading.Lock()
_last = LastCheck()


@dataclass(frozen=True)
class _Probe:
    capability: str
    target: str
    label: str  # the resource name in a reason
    locks: str  # the rows that a failure locks
    time_limit: float  # the limit of one probe, for its reason
    wait: float  # how long the check waits for it, from the start; a queued probe starts late
    run: Callable[[], Optional[str]]


def _servers(
    registry: Iterable[Tuple[str, List[str]]], catalog: Iterable[dict]
) -> dict[str, tuple[str, str]]:
    """Each server (normalized, as a SQL row shows it), with the (server, database) to log in to.

    The servers come from the Database Registry. A server that only the catalog names is tested too,
    because its rows still show on the update page."""
    servers: dict[str, tuple[str, str]] = {}
    declared = [(server, names[0] if names else "master") for server, names in registry]
    declared += [pair for system in catalog for pair in system_targets.declared_databases(system)]
    for server, database in declared:
        target = sql_cache_store.normalize_server(server)
        if target and database:
            servers.setdefault(target, (server, database))
    return servers


def repository_target(source: dict) -> str:
    """The target of a repository in a result: `<project>/<repo>`, as the catalog writes it."""
    return f"{str(source.get('project') or '').strip()}/{str(source.get('repo') or '').strip()}"


def _lock_key(target: str) -> str:
    # Azure DevOps project and repository names ignore case.
    return target.casefold()


def _repositories(catalog: Iterable[dict]) -> dict[str, dict]:
    """Each repository of the catalog, one time also when several systems share it."""
    repositories: dict[str, dict] = {}
    seen: set[str] = set()
    for source in system_targets.sources_of(catalog):
        target = repository_target(source)
        if _lock_key(target) not in seen:
            seen.add(_lock_key(target))
            repositories[target] = source
    return repositories


def _probes(
    registry: Iterable[Tuple[str, List[str]]],
    catalog: list,
    sql_credentials: Mapping[str, SqlCredentialOverride],
) -> list[_Probe]:
    probes = []
    for target, (server, database) in _servers(registry, catalog).items():
        account = sql_credentials.get(target) or SqlCredentialOverride()
        probes.append(
            _Probe(
                "sql_server", target, "SQL Server", f"{target} 的 SQL 列",
                SQL_LOGIN_TIMEOUT_SECONDS, SQL_LOGIN_TIMEOUT_SECONDS + _MARGIN_SECONDS,
                lambda s=server, d=database, a=account: probe_sql_server(s, d, a.db_user_id, a.db_password),
            )
        )
    repositories = _repositories(catalog)
    at_once = threading.Semaphore(GIT_AT_ONCE)
    git_wait = math.ceil(len(repositories) / GIT_AT_ONCE) * GIT_TIMEOUT_SECONDS + _MARGIN_SECONDS

    def git_probe(source: dict) -> Optional[str]:
        with at_once:
            return probe_azure_repos(source)

    for target, source in repositories.items():
        probes.append(
            _Probe(
                "azure_repos", target, "Azure Repos", f"{target} 的 C# 列",
                GIT_TIMEOUT_SECONDS, git_wait, lambda s=source: git_probe(s),
            )
        )
    return probes


def run(
    registry: Iterable[Tuple[str, List[str]]],
    catalog: list,
    sql_credentials: Optional[Mapping[str, SqlCredentialOverride]] = None,
) -> EnvironmentCheckResponse:
    """Run every probe at the same time, keep the lock reasons, and return the result."""
    probes = _probes(registry, catalog, sql_credentials or {})
    outcomes: dict[int, Optional[str]] = {}

    def run_one(index: int, probe: _Probe) -> None:
        try:
            outcomes[index] = probe.run()
        except Exception as exc:  # a broken probe fails its own target only
            outcomes[index] = f"{probe.label} 的測試失敗：{exc}"

    threads = [threading.Thread(target=run_one, args=item, daemon=True) for item in enumerate(probes)]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    items = []
    last = LastCheck()
    for index, (probe, thread) in enumerate(zip(probes, threads)):
        thread.join(max(0.0, started + probe.wait - time.monotonic()))
        reason = _no_answer(probe.label, probe.time_limit) if thread.is_alive() else outcomes[index]
        items.append(
            UpdateCapabilityResult(
                capability=probe.capability,
                target=probe.target,
                ok=reason is None,
                reason=reason or "",
                locks="" if reason is None else probe.locks,
            )
        )
        if reason is not None:
            last.locks.setdefault(probe.capability, {})[_lock_key(probe.target)] = reason
    global _last
    with _lock:
        _last = last
    return EnvironmentCheckResponse(
        checked_at=datetime.now().astimezone().isoformat(timespec="seconds"), capabilities=items
    )


def sql_lock_reason(server: str) -> str:
    """The lock reason of the SQL rows of `server` (normalized), or an empty text."""
    with _lock:
        return _last.locks.get("sql_server", {}).get(_lock_key(server), "")


def csharp_lock_reason(source: Optional[dict]) -> str:
    """The lock reason of the C# row of `source`, or an empty text."""
    if source is None:
        return ""
    with _lock:
        return _last.locks.get("azure_repos", {}).get(_lock_key(repository_target(source)), "")
