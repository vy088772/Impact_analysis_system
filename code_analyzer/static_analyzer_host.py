"""Client for the versioned StaticAnalyzerHost console contract."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


CONTRACT_VERSION = 2
_MAX_HOST_COMMAND_CHARS = 24_000
_MAX_HOST_FILES_PER_BATCH = 10


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