# service/scan_store.py
"""
靜態掃描結果的持久化快取。

第一次掃描某路徑後，將 ProjectScanResult 以 pickle 寫入 data/scan_cache，
之後直接載入，避免每次重新解析 C#（整個 TTPUR 約數百檔、需數分鐘）。
只有在 refresh=True（更新指令）時才重新掃描並覆寫快取。
"""
from __future__ import annotations

import hashlib
import json
import pickle
import time
from pathlib import Path
from typing import Dict, Optional

from config.settings import settings
from code_analyzer.project_scanner import ProjectScanner, ProjectScanResult

# 快取格式版本：模型結構若變動可遞增，使舊快取自動失效
_CACHE_VERSION = 1

# 同 process 內的記憶體快取（避免重複反序列化）
_mem_cache: Dict[str, ProjectScanResult] = {}


def _cache_root() -> Path:
    root = Path(settings.SCAN_CACHE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _key(root: Path) -> str:
    return hashlib.sha1(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


def _paths(root: Path) -> tuple[Path, Path]:
    k = _key(root)
    return _cache_root() / f"{k}.pkl", _cache_root() / f"{k}.meta.json"


def has_cache(root: Path) -> bool:
    pkl, _ = _paths(root)
    return pkl.exists()


def _load(root: Path) -> Optional[ProjectScanResult]:
    pkl, meta = _paths(root)
    if not pkl.exists():
        return None
    try:
        if meta.exists():
            info = json.loads(meta.read_text(encoding="utf-8"))
            if info.get("cache_version") != _CACHE_VERSION:
                return None
        with pkl.open("rb") as f:
            return pickle.load(f)
    except Exception:
        # 反序列化失敗（模型變動等）→ 視為無快取
        return None


def _save(root: Path, result: ProjectScanResult) -> None:
    pkl, meta = _paths(root)
    try:
        with pkl.open("wb") as f:
            pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
        meta.write_text(
            json.dumps(
                {
                    "cache_version": _CACHE_VERSION,
                    "root": str(root.resolve()),
                    "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # 寫檔失敗不致命
        print(f"⚠️  掃描快取寫出失敗（非致命）：{exc}")


def get_or_scan(root: Path, refresh: bool = False) -> ProjectScanResult:
    """
    取得掃描結果：優先用記憶體 / 磁碟快取；refresh=True 則強制重新掃描。
    """
    key = str(root.resolve())

    if not refresh:
        if key in _mem_cache:
            return _mem_cache[key]
        cached = _load(root)
        if cached is not None:
            _mem_cache[key] = cached
            print(f"⚡ 使用快取掃描結果：{root}")
            return cached

    print(f"🔍 重新掃描程式碼：{root}")
    scanner = ProjectScanner(project_root=str(root))
    result = scanner.scan_project(analyze_sp=False)
    _mem_cache[key] = result
    _save(root, result)
    return result


def clear_cache(root: Path) -> None:
    """清除指定路徑的磁碟與記憶體快取。"""
    pkl, meta = _paths(root)
    for p in (pkl, meta):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    _mem_cache.pop(str(root.resolve()), None)
