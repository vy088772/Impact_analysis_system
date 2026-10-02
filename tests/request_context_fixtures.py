"""Request stores shared by migrated handlers and the remaining legacy handlers."""

from dataclasses import dataclass
from pathlib import Path

from code_analyzer.project_scanner import ProjectScanResult
from service import analyze_service, sql_cache_store
from service.request_context_adapters import InMemoryCacheStore, InMemoryScanStore, RealCacheStore
from tests.sql_cache_fixtures import one_server_holds_every_database


@dataclass
class RequestStores:
    scan_store: InMemoryScanStore
    cache_store: InMemoryCacheStore | RealCacheStore

    @classmethod
    def of(cls, root: Path, scan: ProjectScanResult, database: str = "OrdersDb") -> "RequestStores":
        identity = one_server_holds_every_database(database)
        return cls(
            InMemoryScanStore(roots=[root], scans={root: scan}, cached_roots={root}, repository_root=root),
            InMemoryCacheStore({database: identity}),
        )

    def install_legacy(self, monkeypatch) -> None:
        monkeypatch.setattr(analyze_service, "resolve_scan_roots", self.scan_store.resolve_scan_roots)
        monkeypatch.setattr(analyze_service, "_get_scan", self.scan_store.get_scan)
        if isinstance(self.cache_store, InMemoryCacheStore):
            monkeypatch.setattr(sql_cache_store, "find_cache_identity", self.cache_store.find_cache_identity)

    def install_analyze(self, monkeypatch) -> None:
        handler = analyze_service.analyze
        monkeypatch.setattr(
            analyze_service, "analyze",
            lambda request, *args, **kwargs: handler(
                request, *args, scan_store=self.scan_store, cache_store=self.cache_store, **kwargs
            ),
        )

    def install_table(self, monkeypatch) -> None:
        handler = analyze_service.find_by_table
        monkeypatch.setattr(
            analyze_service, "find_by_table",
            lambda request, *args, **kwargs: handler(
                request, *args, scan_store=self.scan_store, cache_store=self.cache_store, **kwargs
            ),
        )

    def install_flow(self, monkeypatch) -> None:
        handler = analyze_service.flow_chain
        monkeypatch.setattr(
            analyze_service, "flow_chain",
            lambda request, *args, **kwargs: handler(
                request, *args, scan_store=self.scan_store, cache_store=self.cache_store, **kwargs
            ),
        )

    def install_http(self, monkeypatch) -> None:
        handler = analyze_service.find_by_sp
        monkeypatch.setattr(
            analyze_service, "find_by_sp",
            lambda request: handler(request, scan_store=self.scan_store, cache_store=self.cache_store),
        )
        self.install_table(monkeypatch)