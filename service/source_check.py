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
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Iterable, Mapping, Optional
from urllib.parse import quote

from code_analyzer.sql_fingerprint import Fingerprint
from config.settings import settings

from . import sql_cache_store

logger = logging.getLogger(__name__)

_LS_REMOTE_TIMEOUT_SECONDS = 30
_MAX_PARALLEL_CHECKS = 4

_lock = threading.Lock()
_heads: dict[tuple[str, str, str], str] = {}
_fingerprints: dict[sql_cache_store.CacheIdentity, Fingerprint] = {}
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


def fetch_remote_head(source: dict) -> Optional[str]:
    """The head commit of the remote branch of `source`, or None when it cannot be read.

    Tests replace this function with a fake remote."""
    if not can_ask_remote(source):
        return None
    project, repo, _ = _key_of(source)
    try:
        result = ls_remote(source)
    except Exception as exc:  # timeout, git missing: this repository keeps no head
        logger.warning("ls-remote of %s/%s failed: %s", project, repo, type(exc).__name__)
        return None
    if result.returncode != 0:
        logger.warning("ls-remote of %s/%s exited with %s", project, repo, result.returncode)
        return None
    fields = result.stdout.split()
    return fields[0] if fields else None


def check(
    sources: Iterable[dict],
    sql_caches: Optional[Mapping[sql_cache_store.CacheIdentity, sql_cache_store.ScanConnection]] = None,
    system_ids: Iterable[str] = (),
) -> None:
    """Ask the remote for the head of each distinct repository, read the current Fingerprint of
    each SQL cache in `sql_caches` through its Scan Connection, and merge the answers into the
    kept answers. A source that gives no answer loses its kept answer. Each system of
    `system_ids` gets the time of this check."""
    distinct = {_key_of(source): source for source in sources if source.get("repo")}
    keys = list(distinct)
    connections = dict(sql_caches or {})
    identities = list(connections)
    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_CHECKS) as pool:
        head_answers = pool.map(lambda key: fetch_remote_head(distinct[key]), keys)
        # Through the module, as `fetch_remote_head`: tests replace the one reader there.
        fingerprint_answers = pool.map(
            lambda identity: sql_cache_store.read_fingerprint(identity, connections[identity]), identities
        )
        heads, fingerprints = list(head_answers), list(fingerprint_answers)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _lock:
        _merge(_heads, zip(keys, heads))
        _merge(_fingerprints, zip(identities, fingerprints))
        _checked_at.update({system_id: now for system_id in system_ids})


def _merge(kept: dict, answers: Iterable[tuple]) -> None:
    """Keep each (key, answer) pair that has an answer. A key with no answer loses its kept answer,
    so a source that a check could not read never shows the answer of an older check."""
    for key, answer in answers:
        if answer:
            kept[key] = answer
        else:
            kept.pop(key, None)


def remote_head(source: dict) -> Optional[str]:
    """The head kept by the last check, or None when no check has run or the repository failed."""
    with _lock:
        return _heads.get(_key_of(source))


def current_fingerprint(identity: sql_cache_store.CacheIdentity) -> Optional[Fingerprint]:
    """The Fingerprint kept by the last check, or None when no check read one for `identity`."""
    with _lock:
        return _fingerprints.get(identity)


def checked_at(system_id: str) -> Optional[str]:
    """The time of the last check of `system_id`, or None when no check read it since the service started."""
    with _lock:
        return _checked_at.get(system_id)
