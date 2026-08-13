"""Persistent cache for external-wrapper decompilation attempts."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping


_CACHE_VERSION = 1


class DecompilationAttemptCache:
    """Store decompilation responses independently from source-scan caches."""

    def __init__(self, root: Path | None = None) -> None:
        configured_root = os.getenv("DECOMPILATION_CACHE_ROOT", "data/decompilation_cache")
        self.root = Path(root) if root is not None else Path(configured_root)

    @property
    def host_root(self) -> Path:
        return self.root / "host"

    def load(self, assembly_identity: str, receiver_type: str) -> dict[str, Any] | None:
        document = self._load_document(assembly_identity)
        if document is None:
            return None
        attempts = document.get("attempts")
        if not isinstance(attempts, Mapping):
            return None
        entry = attempts.get(receiver_type)
        if not isinstance(entry, Mapping):
            return None
        response = entry.get("response")
        if not isinstance(response, Mapping):
            return None
        return dict(response)

    def save(
        self,
        assembly_identity: str,
        receiver_type: str,
        response: Mapping[str, Any],
    ) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            document = self._load_document(assembly_identity) or {
                "cache_version": _CACHE_VERSION,
                "assembly_identity": assembly_identity,
                "attempts": {},
            }
            attempts = document.setdefault("attempts", {})
            if not isinstance(attempts, dict):
                attempts = {}
                document["attempts"] = attempts
            attempts[receiver_type] = {
                "saved_at": time.time(),
                "response": dict(response),
            }
            self._atomic_write(assembly_identity, document)
        except OSError:
            return

    def _load_document(self, assembly_identity: str) -> dict[str, Any] | None:
        path = self._path(assembly_identity)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(document, dict):
            return None
        if document.get("cache_version") != _CACHE_VERSION:
            return None
        if document.get("assembly_identity") != assembly_identity:
            return None
        return document

    def _atomic_write(self, assembly_identity: str, document: Mapping[str, Any]) -> None:
        path = self._path(assembly_identity)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.root,
                prefix=f".{assembly_identity}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                json.dump(document, temporary, ensure_ascii=False, indent=2)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                Path(temporary_path).unlink(missing_ok=True)

    def _path(self, assembly_identity: str) -> Path:
        return self.root / f"{assembly_identity}.json"