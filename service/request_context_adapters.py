"""Real and in-memory stores for request preparation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from code_analyzer.project_scanner import ProjectScanResult
from . import repo_manager, scan_store, sql_cache_store
from .scan_store import ScanOutdated
from .system_targets import has_repository

CacheIdentityResult = sql_cache_store.CacheIdentity | sql_cache_store.AmbiguousServer | None
Source = dict[str, str | list[str]]


class ScanStore(Protocol):
    def resolve_source(self, request: object) -> Source: ...
    def peek_scan_roots(self, source: Source) -> list[Path]: ...
    def read_scan(self, root: Path) -> ProjectScanResult: ...
    def has_cache(self, root: Path) -> bool: ...
    def cache_status(self, root: Path) -> str: ...
    def repo_dir(self, project: str, repo: str) -> Path: ...


class CacheStore(Protocol):
    def find_cache_identity(self, database: str) -> CacheIdentityResult: ...


class RealScanStore:
    def resolve_source(self, request: object) -> Source:
        source = getattr(request, "source", None)
        return {
            "project": source.project if source else "",
            "repo": source.repo if source else "",
            "branch": source.branch if source else "",
            "path": source.path if source else "",
        }

    def peek_scan_roots(self, source: Source) -> list[Path]:
        # The update page's rule: a source without a repository has no scan root, so no
        # C# Scan Result. `repo_manager` would name a `default` folder for it.
        if not has_repository(source):
            return []
        return repo_manager.peek_scan_roots(source)

    def read_scan(self, root: Path) -> ProjectScanResult:
        return scan_store.read_scan(root)

    def has_cache(self, root: Path) -> bool:
        return scan_store.has_cache(root)

    def cache_status(self, root: Path) -> str:
        return scan_store.cache_status(root)

    def repo_dir(self, project: str, repo: str) -> Path:
        return repo_manager.repo_dir(project, repo)


class RealCacheStore:
    def find_cache_identity(self, database: str) -> CacheIdentityResult:
        return sql_cache_store.find_cache_identity(database)


@dataclass
class InMemoryScanStore:
    roots: list[Path] = field(default_factory=list)
    scans: dict[Path, ProjectScanResult] = field(default_factory=dict)
    cached_roots: set[Path] = field(default_factory=set)
    repository_root: Path = Path(".")
    candidate_roots: list[Path] | None = None
    outdated_roots: set[Path] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)

    def resolve_source(self, request: object) -> Source:
        self.calls.append("source")
        return RealScanStore().resolve_source(request)

    def peek_scan_roots(self, source: Source) -> list[Path]:
        self.calls.append("peek")
        return list(self.roots if self.candidate_roots is None else self.candidate_roots)

    def read_scan(self, root: Path) -> ProjectScanResult:
        self.calls.append("read")
        if root in self.outdated_roots:
            raise ScanOutdated(root)
        return self.scans[root]

    def has_cache(self, root: Path) -> bool:
        self.calls.append("cache")
        return root in self.cached_roots

    def cache_status(self, root: Path) -> str:
        self.calls.append("status")
        if root in self.outdated_roots:
            return "stale"
        return "current" if root in self.cached_roots else "missing"

    def repo_dir(self, project: str, repo: str) -> Path:
        self.calls.append("repo")
        return self.repository_root


@dataclass
class InMemoryCacheStore:
    identities: dict[str, CacheIdentityResult] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def find_cache_identity(self, database: str) -> CacheIdentityResult:
        self.calls.append("identity")
        return self.identities.get(database)