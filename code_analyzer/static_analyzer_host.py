"""Client for the versioned StaticAnalyzerHost console contract."""

from __future__ import annotations

import json
import hashlib
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .decompilation_cache import DecompilationAttemptCache


CONTRACT_VERSION = 2
_MAX_HOST_COMMAND_CHARS = 24_000
# Every host invocation re-parses every `.cs` file under the given source roots as analysis
# context before it looks at a single --input file, so that context cost is paid once per
# invocation, not once per file: on the 541-file Y-Docs TTPUR project it is about 14 seconds
# against about 0.07 seconds per input file. Ten files per batch meant 55 invocations and 55
# context parses; a hundred means six. _MAX_HOST_COMMAND_CHARS still bounds each batch, so a
# project with long paths splits earlier on its own rather than overrunning the command line.
_MAX_HOST_FILES_PER_BATCH = 100


class StaticAnalyzerHostError(RuntimeError):
    """Raised when the analyzer host cannot satisfy its public contract."""


@dataclass(frozen=True)
class StaticAnalyzerHost:
    """Builds and invokes the repository-owned .NET analyzer host."""

    project_path: Path

    @classmethod
    def for_project(cls, project_root: Path) -> "StaticAnalyzerHost":
        return cls(project_root / "tools" / "StaticAnalyzerHost" / "StaticAnalyzerHost.csproj")

    @property
    def dll_path(self) -> Path:
        return self.project_path.parent / "bin" / "Debug" / "net8.0" / "StaticAnalyzerHost.dll"

    def build(self) -> Path:
        if not self.project_path.exists():
            raise StaticAnalyzerHostError(f"StaticAnalyzerHost project not found: {self.project_path}")
        try:
            result = subprocess.run(
                ["dotnet", "build", str(self.project_path), "--nologo"],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except FileNotFoundError as exc:
            raise StaticAnalyzerHostError("dotnet runtime is not available for StaticAnalyzerHost") from exc
        if result.returncode != 0 or not self.dll_path.exists():
            message = result.stderr.strip() or result.stdout.strip() or "StaticAnalyzerHost build failed"
            raise StaticAnalyzerHostError(message)
        return self.dll_path

    def ensure_ready(self) -> dict[str, Any]:
        """Build locally when needed, then validate the deployed host contract."""
        if not self.dll_path.exists() or self._source_is_newer_than_artifact():
            self.build()
        return self.version()

    def version(self) -> dict[str, Any]:
        payload = self._run("--version")
        if payload.get("contract_version") != CONTRACT_VERSION:
            raise StaticAnalyzerHostError(
                f"StaticAnalyzerHost contract mismatch: expected {CONTRACT_VERSION}, got {payload.get('contract_version')}"
            )
        return payload

    def analyze_csharp(self, input_path: Path) -> dict[str, Any]:
        return self._run("csharp", "--input", str(input_path))

    def analyze_csharp_files(
        self,
        input_paths: list[Path],
        source_roots: list[Path] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[dict[str, Any]]:
        if not input_paths:
            return []
        source_roots = source_roots or []
        results: list[dict[str, Any]] = []
        batch: list[Path] = []
        base_command_length = len("csharp") + sum(
            len(" --source-root ") + len(str(source_root))
            for source_root in source_roots
        )
        command_length = base_command_length
        completed = 0

        for input_path in input_paths:
            input_length = len(str(input_path)) + len(" --input ")
            if batch and (
                len(batch) >= _MAX_HOST_FILES_PER_BATCH
                or command_length + input_length > _MAX_HOST_COMMAND_CHARS
            ):
                results.extend(self._analyze_csharp_batch(batch, source_roots))
                completed += len(batch)
                if progress_callback is not None:
                    progress_callback(completed, len(input_paths), str(batch[-1]))
                batch = []
                command_length = base_command_length
            batch.append(input_path)
            command_length += input_length

        if batch:
            results.extend(self._analyze_csharp_batch(batch, source_roots))
            completed += len(batch)
            if progress_callback is not None:
                progress_callback(completed, len(input_paths), str(batch[-1]))
        return results

    def analyze_sql(self, input_path: Path) -> dict[str, Any]:
        return self._run("sql", "--input", str(input_path))

    def semantic_binding_availability(self, scan_roots: list[Path]) -> list[dict[str, Any]]:
        """Report Semantic Binding Availability for each project file found under each
        scan root: whether the analyzer could build a compilation with a real semantic
        model, or why not. One call covers every scan root; the host builds one
        compilation per project file, never one per source file."""
        if not scan_roots:
            return []
        args = ["semantic-binding"]
        for scan_root in scan_roots:
            args.extend(["--source-root", str(scan_root)])
        payload = self._run(*args)
        result = payload.get("semantic_binding_availability")
        return result if isinstance(result, list) else []

    def decompile_wrapper(
        self,
        csproj_path: Path,
        receiver_type: str,
        *,
        rerun: bool = False,
        cache_root: Path | None = None,
    ) -> dict[str, Any]:
        dll_path = _referenced_dll_path(csproj_path, receiver_type)
        assembly_identity = _sha256_file(dll_path) if dll_path is not None else None
        cache = DecompilationAttemptCache(cache_root)
        cached_response = None
        if assembly_identity is not None:
            cached_response = cache.load(assembly_identity, receiver_type)
        if cached_response is not None and not rerun:
            return _with_decompilation_metadata(
                cached_response,
                assembly_identity,
                cache_status="hit",
                attempted=False,
            )

        host_args = [
            "decompile-wrapper",
            "--csproj",
            str(csproj_path),
            "--receiver-type",
            receiver_type,
            "--cache-root",
            str(cache.host_root),
        ]
        if rerun:
            host_args.append("--rerun")
        response = self._run(*host_args)
        host_cache_status = response.get("cache_status")
        if cached_response is None and host_cache_status in {
            "hit",
            "bypassed",
            "miss",
            "not_applicable",
        }:
            cache_status = host_cache_status
            host_attempt = response.get("decompilation_attempt")
            attempted = (
                bool(host_attempt.get("attempted"))
                if isinstance(host_attempt, dict)
                else assembly_identity is not None
            )
        else:
            cache_status = "bypassed" if cached_response is not None else (
                "miss" if assembly_identity is not None else "not_applicable"
            )
            attempted = assembly_identity is not None
        response = _with_decompilation_metadata(
            response,
            assembly_identity,
            cache_status=cache_status,
            attempted=attempted,
        )
        if assembly_identity is not None:
            cache.save(assembly_identity, receiver_type, response)
        return response

    def _run(self, *args: str) -> dict[str, Any]:
        if not self.dll_path.exists():
            raise StaticAnalyzerHostError(f"StaticAnalyzerHost build output not found: {self.dll_path}")
        try:
            result = subprocess.run(
                ["dotnet", str(self.dll_path), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except OSError as exc:
            raise StaticAnalyzerHostError(f"StaticAnalyzerHost could not start: {exc}") from exc
        if result.returncode != 0:
            raise StaticAnalyzerHostError(result.stderr.strip() or "StaticAnalyzerHost invocation failed")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise StaticAnalyzerHostError("StaticAnalyzerHost returned invalid JSON") from exc
        if payload.get("contract_version") != CONTRACT_VERSION:
            raise StaticAnalyzerHostError(
                f"StaticAnalyzerHost contract mismatch: expected {CONTRACT_VERSION}, got {payload.get('contract_version')}"
            )
        return payload

    def _analyze_csharp_batch(
        self,
        input_paths: list[Path],
        source_roots: list[Path],
    ) -> list[dict[str, Any]]:
        args = ["csharp"]
        for source_root in source_roots:
            args.extend(["--source-root", str(source_root)])
        for input_path in input_paths:
            args.extend(["--input", str(input_path)])
        payload = self._run(*args)
        if len(input_paths) == 1:
            return [payload]
        sources = payload.get("sources")
        if not isinstance(sources, list) or len(sources) != len(input_paths):
            raise StaticAnalyzerHostError("StaticAnalyzerHost returned an invalid C# batch response")
        return sources

    def _source_is_newer_than_artifact(self) -> bool:
        artifact_mtime = self.dll_path.stat().st_mtime
        source_paths = [self.project_path, *self.project_path.parent.rglob("*.cs")]
        return any(path.stat().st_mtime > artifact_mtime for path in source_paths)


_NOT_ATTEMPTED_STATUSES = {
    "csproj_not_found",
    "csproj_unreadable",
    "receiver_not_referenced",
    "hint_path_missing",
    "referenced_dll_missing",
}


def _referenced_dll_path(csproj_path: Path, receiver_type: str) -> Path | None:
    try:
        root = ET.parse(csproj_path).getroot()
    except (OSError, ET.ParseError):
        return None

    for reference in root.iter():
        if _xml_local_name(reference.tag) != "Reference":
            continue
        include = reference.attrib.get("Include", "")
        if include.split(",", 1)[0].strip() != receiver_type:
            continue
        hint_path = next(
            (
                child.text
                for child in reference
                if _xml_local_name(child.tag) == "HintPath"
            ),
            None,
        )
        if not hint_path or not hint_path.strip():
            return None
        normalized_hint_path = hint_path.strip().replace("\\", "/")
        dll_path = (csproj_path.parent / normalized_hint_path).resolve()
        return dll_path if dll_path.is_file() else None
    return None


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sha256_file(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _with_decompilation_metadata(
    response: dict[str, Any],
    assembly_identity: str | None,
    *,
    cache_status: str,
    attempted: bool,
) -> dict[str, Any]:
    result = dict(response)
    outcome = _attempt_outcome(result)
    result["attempt_outcome"] = outcome
    result["cache_status"] = cache_status
    result["decompilation_attempt"] = {
        "attempted": attempted,
        "outcome": outcome,
        "cache_status": cache_status,
        "assembly_identity": assembly_identity,
    }
    return result


def _attempt_outcome(response: dict[str, Any]) -> str:
    status = response.get("status")
    if status in _NOT_ATTEMPTED_STATUSES:
        return "not_attempted"
    if status != "resolved":
        return "incomplete"
    definitions = response.get("wrapper_definitions") or []
    translation_problems = response.get("translation_problem_methods") or []
    if not definitions or translation_problems:
        return "incomplete"
    if any(definition.get("unresolved_reason") for definition in definitions):
        return "incomplete"
    return "complete"