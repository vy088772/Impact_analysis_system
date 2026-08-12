"""Recoverable two-file atomic commit for staged contract registry/catalog.

Registry and catalog selector updates are only ever applied after formal
classification and wrapper reconciliation succeed (see ``contract_preflight``
and ``analyze_service.refresh_source``).  This module owns the commit itself:
a transaction manifest is written before either active file is replaced, both
files are replaced through validated temporary artifacts, and a post-commit
validation step confirms the active bytes match the staged content.  If the
process is interrupted after one file has been replaced, ``recover_transaction``
uses the manifest and the staged/backup artifacts to reach the same new pair;
it never leaves a mixed active state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "config" / "external_wrapper_contracts.json"
DEFAULT_CATALOG_PATH = PROJECT_ROOT.parent / "llamaindex-spec-rag" / "catalog" / "system_catalog.json"


def _repository_revision(path: Path) -> str:
    """Best-effort git HEAD revision for the repository containing ``path``.

    Returns an empty string when the path is not inside a git repository or
    git is unavailable; a missing revision never blocks a commit.
    """
    directory = path if path.is_dir() else path.parent
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(directory),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


class ContractTransactionError(ValueError):
    """A staged registry/catalog commit could not be completed safely."""

    def __init__(self, code: str, message: str, details: Iterable[str] = ()):
        self.code = code
        self.details = tuple(str(item) for item in details)
        super().__init__(message)


def _error(code: str, message: str, details: Iterable[str] = ()) -> None:
    raise ContractTransactionError(code, message, details)


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def _registry_payload(registry: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(registry, Mapping):
        return {"contracts": {}}
    payload = copy.deepcopy(dict(registry))
    contracts = payload.get("contracts")
    if not isinstance(contracts, Mapping):
        payload["contracts"] = {}
        return payload
    payload["contracts"] = {str(name): copy.deepcopy(value) for name, value in contracts.items()}
    return payload


def _validate_staged_registry(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("contracts"), Mapping):
        _error("registry_invalid", "staged registry 必須包含 contracts object")
    for name, contract in payload["contracts"].items():
        if not isinstance(name, str) or not name.strip():
            _error("invalid_contract_name", "staged contract name 不可為空")
        if not isinstance(contract, Mapping):
            _error("invalid_contract", f"staged contract {name!r} 必須是 object")


def _selector_value(selector: Any) -> Any:
    if selector is None:
        return None
    if isinstance(selector, str):
        return selector.strip() or None
    if isinstance(selector, (list, tuple)):
        values = [str(item).strip() for item in selector if str(item).strip()]
        return sorted(values, key=str.casefold) if values else None
    return None


def _catalog_with_selector(
    catalog_payload: Mapping[str, Any],
    system_id: str,
    selector: Any,
) -> dict[str, Any]:
    systems = catalog_payload.get("systems")
    if not isinstance(systems, list):
        _error("catalog_invalid", "system catalog 必須包含 systems array")
    after = copy.deepcopy(dict(catalog_payload))
    after_systems = after["systems"]
    target = next(
        (
            item
            for item in after_systems
            if isinstance(item, Mapping) and str(item.get("system_id") or "").strip() == system_id
        ),
        None,
    )
    if target is None:
        _error("system_not_found", f"system selector target 不存在：{system_id}")
    target["wrapper_contract"] = copy.deepcopy(selector)
    return after


def _manifest_dir(registry_path: Path, manifest_dir: Path | str | None) -> Path:
    if manifest_dir is not None:
        return Path(manifest_dir)
    return registry_path.parent / ".contract_transactions"


def _write_manifest(manifest_path: Path, manifest: Mapping[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(manifest_path, _json_text(manifest).encode("utf-8"))


def _read_manifest(manifest_path: Path) -> dict[str, Any]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def commit_staged_contract_transaction(
    *,
    staged_registry: Mapping[str, Any],
    staged_selector: Any = None,
    system_id: str = "",
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
    catalog_path: Path | str = DEFAULT_CATALOG_PATH,
    source_revision: Mapping[str, str] | None = None,
    manifest_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Commit a staged registry (and optional catalog selector) atomically.

    Both files are replaced only after a transaction manifest and validated
    staged/backup artifacts have been written.  A failure during replacement
    or post-commit validation rolls the active files back to their previous
    bytes; both remain byte-for-byte unchanged in that case.
    """
    registry_file = Path(registry_path)
    normalized_system_id = str(system_id or "").strip()
    normalized_selector = _selector_value(staged_selector)
    staged_registry_payload = _registry_payload(staged_registry)
    _validate_staged_registry(staged_registry_payload)

    before_registry_bytes = _read_bytes(registry_file)
    staged_registry_text = _json_text(staged_registry_payload)
    try:
        before_registry_payload = json.loads(before_registry_bytes.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        before_registry_payload = None
    registry_changed = _registry_payload(before_registry_payload) != staged_registry_payload

    catalog_file: Optional[Path] = None
    before_catalog_bytes = b""
    after_catalog_payload: Optional[dict[str, Any]] = None
    catalog_changed = False
    if normalized_selector is not None and normalized_system_id:
        catalog_file = Path(catalog_path)
        before_catalog_payload = json.loads(_read_bytes(catalog_file).decode("utf-8") or "{}")
        after_catalog_payload = _catalog_with_selector(
            before_catalog_payload, normalized_system_id, normalized_selector
        )
        before_catalog_bytes = _read_bytes(catalog_file)
        after_catalog_text = _json_text(after_catalog_payload)
        catalog_changed = before_catalog_payload != after_catalog_payload

    if not registry_changed and not catalog_changed:
        return {
            "status": "noop",
            "transaction_id": "",
            "manifest_path": "",
            "written_files": [],
        }

    staged_registry_digest = _sha256_text(staged_registry_text)
    staged_catalog_text = _json_text(after_catalog_payload) if catalog_changed else ""
    staged_catalog_digest = _sha256_text(staged_catalog_text) if catalog_changed else ""
    transaction_id = _sha256_text(
        "|".join(
            (
                staged_registry_digest,
                staged_catalog_digest,
                normalized_system_id,
                str(normalized_selector),
            )
        )
    )[:32]

    directory = _manifest_dir(registry_file, manifest_dir)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / f"{transaction_id}.manifest.json"
    staged_registry_artifact = directory / f"{transaction_id}.registry.staged.json"
    backup_registry_artifact = directory / f"{transaction_id}.registry.backup.json"
    _atomic_write_bytes(staged_registry_artifact, staged_registry_text.encode("utf-8"))
    _atomic_write_bytes(backup_registry_artifact, before_registry_bytes)

    staged_catalog_artifact = directory / f"{transaction_id}.catalog.staged.json"
    backup_catalog_artifact = directory / f"{transaction_id}.catalog.backup.json"
    if catalog_changed:
        _atomic_write_bytes(staged_catalog_artifact, staged_catalog_text.encode("utf-8"))
        _atomic_write_bytes(backup_catalog_artifact, before_catalog_bytes)

    replacement_order = ["registry"] + (["catalog"] if catalog_changed else [])
    manifest: dict[str, Any] = {
        "transaction_id": transaction_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "system_id": normalized_system_id,
        "source_revision": dict(source_revision or {}),
        "target_repository_revision": {
            "registry_repository": _repository_revision(registry_file),
            "catalog_repository": _repository_revision(catalog_file) if catalog_changed and catalog_file else "",
        },
        "registry_path": str(registry_file),
        "catalog_path": str(catalog_file) if catalog_changed else "",
        "staged_registry_digest": staged_registry_digest,
        "staged_catalog_digest": staged_catalog_digest,
        "previous_registry_hash": _sha256_bytes(before_registry_bytes),
        "previous_catalog_hash": _sha256_bytes(before_catalog_bytes) if catalog_changed else "",
        "staged_registry_artifact": str(staged_registry_artifact),
        "backup_registry_artifact": str(backup_registry_artifact),
        "staged_catalog_artifact": str(staged_catalog_artifact) if catalog_changed else "",
        "backup_catalog_artifact": str(backup_catalog_artifact) if catalog_changed else "",
        "replacement_order": replacement_order,
        "commit_progress": [],
        "recovery_location": str(manifest_path),
        "final_status": "pending",
    }
    _write_manifest(manifest_path, manifest)

    written_files: list[str] = []
    try:
        if registry_changed:
            _atomic_write_bytes(registry_file, staged_registry_text.encode("utf-8"))
            written_files.append(str(registry_file))
            manifest["commit_progress"].append("registry_replaced")
            _write_manifest(manifest_path, manifest)
        if catalog_changed and catalog_file is not None:
            _atomic_write_bytes(catalog_file, staged_catalog_text.encode("utf-8"))
            written_files.append(str(catalog_file))
            manifest["commit_progress"].append("catalog_replaced")
            _write_manifest(manifest_path, manifest)

        if registry_changed and _sha256_bytes(_read_bytes(registry_file)) != staged_registry_digest:
            _error("post_commit_validation_failed", "registry post-commit validation 失敗")
        if catalog_changed and catalog_file is not None:
            if _sha256_bytes(_read_bytes(catalog_file)) != staged_catalog_digest:
                _error("post_commit_validation_failed", "catalog post-commit validation 失敗")
    except Exception as exc:
        rollback_errors: list[str] = []
        if "catalog_replaced" in manifest["commit_progress"] and catalog_file is not None:
            try:
                _atomic_write_bytes(catalog_file, before_catalog_bytes)
            except Exception as rollback_exc:  # pragma: no cover - defensive
                rollback_errors.append(f"{catalog_file}: {rollback_exc}")
        if "registry_replaced" in manifest["commit_progress"]:
            try:
                _atomic_write_bytes(registry_file, before_registry_bytes)
            except Exception as rollback_exc:  # pragma: no cover - defensive
                rollback_errors.append(f"{registry_file}: {rollback_exc}")
        manifest["commit_progress"].append("rolled_back")
        manifest["final_status"] = "rolled_back"
        manifest["rollback_errors"] = rollback_errors
        _write_manifest(manifest_path, manifest)
        if rollback_errors:
            _error(
                "commit_rollback_failed",
                f"staged contract commit 失敗且 rollback 不完整：{exc}",
                rollback_errors,
            )
        _error("commit_failed", f"staged contract commit 失敗，已完成 rollback：{exc}")

    manifest["commit_progress"].append("post_commit_validated")
    manifest["final_status"] = "committed"
    _write_manifest(manifest_path, manifest)

    return {
        "status": "committed",
        "transaction_id": transaction_id,
        "manifest_path": str(manifest_path),
        "written_files": written_files,
    }


def recover_transaction(manifest_path: Path | str) -> dict[str, Any]:
    """Recover an interrupted commit, always completing the same new pair.

    The staged artifacts were validated before the first file was replaced,
    so recovery never falls back to the old pair; it finishes writing
    whichever target has not yet been replaced and re-validates both files.
    """
    manifest_file = Path(manifest_path)
    manifest = _read_manifest(manifest_file)

    if manifest.get("final_status") == "committed":
        return {"status": "already_committed", "transaction_id": manifest["transaction_id"]}
    if manifest.get("final_status") == "rolled_back":
        return {"status": "already_rolled_back", "transaction_id": manifest["transaction_id"]}

    progress: list[str] = list(manifest.get("commit_progress", []))
    registry_path = Path(manifest["registry_path"])
    catalog_path_value = str(manifest.get("catalog_path") or "")
    replacement_order = manifest.get("replacement_order", [])

    if "registry_replaced" not in progress:
        staged_registry_bytes = Path(manifest["staged_registry_artifact"]).read_bytes()
        _atomic_write_bytes(registry_path, staged_registry_bytes)
        progress.append("registry_replaced")

    if "catalog" in replacement_order and "catalog_replaced" not in progress:
        staged_catalog_bytes = Path(manifest["staged_catalog_artifact"]).read_bytes()
        _atomic_write_bytes(Path(catalog_path_value), staged_catalog_bytes)
        progress.append("catalog_replaced")

    registry_ok = _sha256_bytes(_read_bytes(registry_path)) == manifest["staged_registry_digest"]
    catalog_ok = True
    if catalog_path_value:
        catalog_ok = _sha256_bytes(_read_bytes(Path(catalog_path_value))) == manifest["staged_catalog_digest"]

    manifest["commit_progress"] = progress
    if registry_ok and catalog_ok:
        manifest["final_status"] = "committed"
        status = "recovered_committed"
    else:
        manifest["final_status"] = "recovery_required"
        status = "recovery_required"
    _write_manifest(manifest_file, manifest)
    return {"status": status, "transaction_id": manifest["transaction_id"]}


__all__ = [
    "ContractTransactionError",
    "DEFAULT_CATALOG_PATH",
    "DEFAULT_REGISTRY_PATH",
    "commit_staged_contract_transaction",
    "recover_transaction",
]
