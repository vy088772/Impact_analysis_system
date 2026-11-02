"""The `behind_source` check: did the source change after the scan? (Impact ADR-0045)

For a C# Scan Result, the source is the remote repository. The check asks it for the head commit
of a branch (`git ls-remote`, no clone, no pull). For a SQL cache, the source is the Database. The
check reads its current Fingerprint from the system catalog (`sql_cache_store.read_fingerprint`).

The check runs only when the web asks for it (`POST /cache_freshness/check`); a question never
runs it. A check can read every catalog system or one system. It merges its answers into the
answers that it keeps: it replaces only the heads and the Fingerprints that it read, so a check of
one system keeps the results of the other systems. The service keeps one check time for each
catalog system. All of this stays in memory, so a restart forgets it and the rows show no
`behind_source` until the next check.

The comparison with the recorded commit or the recorded Fingerprint happens when a listing is
built (`cache_freshness`), so a finished Refresh Job clears `behind_source` with no second check.
A repository or a Database that cannot be read keeps no value: its row is never `behind_source`.
The check keeps the short reason of the failure instead, and the row shows it (issue #10 of
`TCCDIV1/AI_LlamaIndex`). A failure is not a Cache Freshness: it changes no state of the row.
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import quote

from code_analyzer.sql_fingerprint import Fingerprint
from config.settings import settings

from . import sql_cache_store
from .failure_reasons import no_answer

logger = logging.getLogger(__name__)

_LS_REMOTE_TIMEOUT_SECONDS = 30
_MAX_PARALLEL_CHECKS = 4

_lock = threading.Lock()
_heads: dict[tuple[str, str, str], str] = {}
_fingerprints: dict[sql_cache_store.CacheIdentity, Fingerprint] = {}
# The reason of each source that the last check of it could not read. A source has a kept answer
# or a failure, never both.
_head_failures: dict[tuple[str, str, str], str] = {}
_fingerprint_failures: dict[sql_cache_store.CacheIdentity, str] = {}
_checked_at: dict[str, str] = {}


def _branch_of(source: dict) -> str:
    return str(source.get("branch") or "") or settings.AZURE_DEVOPS_BRANCH or "main"


def _key_of(source: dict) -> tuple[str, str, str]:
    return (str(source.get("project") or ""), str(source.get("repo") or ""), _branch_of(source))


def remote_url(source: dict) -> str:
    """The Azure Repos URL of the repository of `source`."""
    project, repo, _ = _key_of(source)
    org = settings.AZURE_DEVOPS_ORG
    return f"https://dev.azure.com/{org}/{quote(project, safe='')}/_git/{quote(repo, safe='')}"


def can_ask_remote(source: dict) -> bool:
    """True when the settings and `source` name enough to ask the remote."""
    project, repo, _ = _key_of(source)
    return bool(settings.AZURE_DEVOPS_ORG and settings.AZURE_DEVOPS_PAT and project and repo)


class SourceUnreadable(Exception):
    """The check could not read a repository. The message is the short reason that the page shows."""


def ls_remote(source: dict, timeout: float = _LS_REMOTE_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """Run `git ls-remote` for the branch of `source`. A timeout or a missing git raises.

    The caller first makes sure that `can_ask_remote(source)` is true."""
    # The PAT travels in the environment, not in the command line (`ps` shows arguments).
    token = base64.b64encode(f":{settings.AZURE_DEVOPS_PAT}".encode()).decode()
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraheader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {token}",
    }
    return subprocess.run(
        ["git", "ls-remote", remote_url(source), f"refs/heads/{_branch_of(source)}"],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def read_ls_remote(source: dict, timeout: float = _LS_REMOTE_TIMEOUT_SECONDS) -> str:
    """The output of `git ls-remote` for the branch of `source`.

    Missing settings, a timeout, a missing git and a failed exit raise `SourceUnreadable` with a
    short reason. The reason never holds the PAT. The Environment Check gives the same reasons."""
    if not can_ask_remote(source):
        raise SourceUnreadable("Impact 服務沒有設定 AZURE_DEVOPS_ORG 或 AZURE_DEVOPS_PAT")
    try:
        result = ls_remote(source, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SourceUnreadable(no_answer("Azure Repos", timeout)) from None
    except FileNotFoundError:
        raise SourceUnreadable("這台機器沒有 git") from None
    if result.returncode != 0:
        lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
        detail = (lines[-1] if lines else f"exit {result.returncode}").replace(settings.AZURE_DEVOPS_PAT or "\0", "***")
        raise SourceUnreadable(f"git ls-remote 失敗：{detail}")
    return result.stdout


def fetch_remote_head(source: dict) -> str:
    """The head commit of the remote branch of `source`. A source that cannot be read raises
    `SourceUnreadable` with a short reason.

    Tests replace this function with a fake remote."""
    fields = read_ls_remote(source).split()
    if not fields:
        raise SourceUnreadable(f"遠端沒有分支 {_branch_of(source)}")
    return fields[0]


def check(
    sources: Iterable[dict],
    sql_caches: Optional[Mapping[sql_cache_store.CacheIdentity, sql_cache_store.ScanConnection]] = None,
    system_ids: Iterable[str] = (),
) -> None:
    """Ask the remote for the head of each distinct repository, read the current Fingerprint of
    each SQL cache in `sql_caches` through its Scan Connection, and merge the answers into the
    kept answers. A source that cannot be read loses its kept answer and keeps the reason of the
    failure instead. Each system of `system_ids` gets the time of this check."""
    distinct = {_key_of(source): source for source in sources if source.get("repo")}
    keys = list(distinct)
    connections = dict(sql_caches or {})
    identities = list(connections)
    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_CHECKS) as pool:
        head_answers = pool.map(lambda key: _read(fetch_remote_head, distinct[key]), keys)
        # Through the module, as `fetch_remote_head`: tests replace the one reader there.
        fingerprint_answers = pool.map(
            lambda identity: _read(sql_cache_store.read_fingerprint, identity, connections[identity]), identities
        )
        heads, fingerprints = list(head_answers), list(fingerprint_answers)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _lock:
        _merge(_heads, _head_failures, zip(keys, heads))
        _merge(_fingerprints, _fingerprint_failures, zip(identities, fingerprints))
        _checked_at.update({system_id: now for system_id in system_ids})


def _read(reader, *args) -> tuple[Any, str]:
    """(answer, "") when `reader` reads its source, or (None, reason) when it cannot."""
    try:
        return reader(*args), ""
    except (SourceUnreadable, sql_cache_store.FingerprintUnreadable) as exc:
        return None, str(exc)
    except Exception as exc:  # an unexpected failure of one source must not stop the check
        logger.warning("source check read failed: %s", type(exc).__name__)
        return None, f"讀取失敗（{type(exc).__name__}）"


def _merge(kept: dict, failures: dict, answers: Iterable[tuple[Any, tuple[Any, str]]]) -> None:
    """Keep the answer or the failure of each key. A key has one of them, never both, so a source
    that a check could not read never shows the answer of an older check, and a later successful
    read clears the failure."""
    for key, (answer, reason) in answers:
        if reason:
            kept.pop(key, None)
            failures[key] = reason
        else:
            kept[key] = answer
            failures.pop(key, None)


def remote_head(source: dict) -> Optional[str]:
    """The head kept by the last check, or None when no check has run or the repository failed."""
    with _lock:
        return _heads.get(_key_of(source))


def remote_failure(source: dict) -> str:
    """The reason why the last check could not read the repository of `source`, or an empty text."""
    with _lock:
        return _head_failures.get(_key_of(source), "")


def current_fingerprint(identity: sql_cache_store.CacheIdentity) -> Optional[Fingerprint]:
    """The Fingerprint kept by the last check, or None when no check read one for `identity`."""
    with _lock:
        return _fingerprints.get(identity)


def fingerprint_failure(identity: sql_cache_store.CacheIdentity) -> str:
    """The reason why the last check could not read the Fingerprint of `identity`, or an empty text."""
    with _lock:
        return _fingerprint_failures.get(identity, "")


def checked_at(system_id: str) -> Optional[str]:
    """The time of the last check of `system_id`, or None when no check read it since the service started."""
    with _lock:
        return _checked_at.get(system_id)
