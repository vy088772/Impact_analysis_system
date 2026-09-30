"""SQL Text Analysis: SQL texts in, one typed result for each text out.

A caller gives a sequence of SQL texts and gets one result for each text, in
input order. A result holds the operations and the parse errors that the
analyzer host reports for the text, as typed records. SQL Text Analysis returns
what the host reports and removes nothing: a `#temp` table stays in the answer.

Two adapters give the answer:

- `HostSqlTextAnalysis` runs the analyzer host's batch SQL command. The command
  takes file paths only, so this adapter writes each text to a temporary file.
  It is the only product code that reads the host's SQL answer by string keys.
- `InMemorySqlTextAnalysis` holds a table from a text to its operations. A test
  uses it, so the test starts no host and writes no file.

No path of a temporary file leaves this module: a source location holds no
path, an error names its text by index, and a text outside a SQL module gets
no module name.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from canonical_object_identity import ObjectName

from .static_analyzer_host import StaticAnalyzerHost, StaticAnalyzerHostError


# A completed count and a total count. It holds no name: each caller turns a
# count into its own name.
ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class SqlModuleIdentity:
    """The SQL module that holds an operation. A text outside a module has the type `unknown`."""

    type: str = "unknown"
    schema: str = ""
    name: str = ""


@dataclass(frozen=True)
class SqlSourceLocation:
    """Where an operation is in its text. The offsets count the characters of the text the caller gave."""

    start_line: int = 0
    start_column: int = 0
    start_offset: int = 0
    length: int = 0
    end_line: int = 0
    end_column: int = 0


@dataclass(frozen=True)
class SqlOperation:
    """One operation of a SQL text, with every field the analyzer host reports for it."""

    operation_type: str
    module: SqlModuleIdentity = SqlModuleIdentity()
    sequence: int = 1
    branch_path: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    where: str | None = None
    read_tables: tuple[ObjectName, ...] = ()
    write_tables: tuple[ObjectName, ...] = ()
    unresolved_write_targets: tuple[str, ...] = ()
    read_columns: tuple[str, ...] = ()
    written_columns: tuple[str, ...] = ()
    function_references: tuple[ObjectName, ...] = ()
    call_targets: tuple[ObjectName, ...] = ()
    dynamic_sql: bool = False
    source: SqlSourceLocation = SqlSourceLocation()


@dataclass(frozen=True)
class SqlParseError:
    """One error the parser reports for a SQL text, with the line of the text it names."""

    line: int
    message: str


@dataclass(frozen=True)
class SqlTextResult:
    """The answer for one SQL text. A text that fails to parse gives parse errors, not a failure."""

    operations: tuple[SqlOperation, ...] = ()
    parse_errors: tuple[SqlParseError, ...] = ()


class SqlTextAnalysisError(StaticAnalyzerHostError):
    """The host failed on one text. `index` is the position of that text in the input."""

    def __init__(self, index: int, message: str) -> None:
        super().__init__(message)
        self.index = index


class SqlTextAnalysis(Protocol):
    def analyze(
        self,
        texts: Sequence[str],
        progress_callback: ProgressCallback | None = None,
    ) -> list[SqlTextResult]:
        """Return one result for each text, in input order."""
        ...


class HostSqlTextAnalysis:
    """The adapter that runs the analyzer host's batch SQL command."""

    def __init__(self, host: StaticAnalyzerHost) -> None:
        self._host = host
        self._host_is_ready = False

    @classmethod
    def for_project(cls, project_root: Path) -> "HostSqlTextAnalysis":
        return cls(StaticAnalyzerHost.for_project(project_root))

    def analyze(
        self,
        texts: Sequence[str],
        progress_callback: ProgressCallback | None = None,
    ) -> list[SqlTextResult]:
        if not texts:
            return []
        if not self._host_is_ready:
            self._host.ensure_ready()
            self._host_is_ready = True
        with tempfile.TemporaryDirectory(prefix="sql-text-") as temp_dir:
            input_paths: list[Path] = []
            for index, text in enumerate(texts):
                input_path = Path(temp_dir) / f"{index:05d}.sql"
                # newline="" writes each line end as the text holds it, so the
                # host's offsets stay aligned with the text.
                input_path.write_text(text, encoding="utf-8", newline="")
                input_paths.append(input_path)

            def report_batch(completed: int, total: int, last_input: str) -> None:
                if progress_callback is not None:
                    progress_callback(completed, total)

            try:
                raw_results = self._host.analyze_sql_files(input_paths, report_batch)
            except StaticAnalyzerHostError as exc:
                # The host names the failed input by path; a caller knows its texts by index.
                # The message counts from one, as a person does.
                message = str(exc)
                for index, input_path in enumerate(input_paths):
                    if str(input_path) in message:
                        named = f"text {index + 1} of {len(texts)}"
                        raise SqlTextAnalysisError(index, message.replace(str(input_path), named)) from exc
                raise
        if len(raw_results) != len(texts):
            raise StaticAnalyzerHostError("StaticAnalyzerHost returned a SQL result count that differs from the text count")
        return [_result(raw_result) for raw_result in raw_results]


class InMemorySqlTextAnalysis:
    """The adapter that answers from a table. A text the table does not hold has no operation."""

    def __init__(self, operations_by_text: Mapping[str, Iterable[SqlOperation]]) -> None:
        self._operations_by_text = {
            text: tuple(operations) for text, operations in operations_by_text.items()
        }

    def analyze(
        self,
        texts: Sequence[str],
        progress_callback: ProgressCallback | None = None,
    ) -> list[SqlTextResult]:
        results = [
            SqlTextResult(operations=self._operations_by_text.get(text, ())) for text in texts
        ]
        if progress_callback is not None and texts:
            progress_callback(len(texts), len(texts))
        return results


def _result(raw: dict[str, Any]) -> SqlTextResult:
    return SqlTextResult(
        operations=tuple(_operation(operation) for operation in raw["operations"]),
        parse_errors=tuple(
            SqlParseError(line=error["line"], message=error["message"])
            for error in raw["parse_errors"]
        ),
    )


def _operation(raw: dict[str, Any]) -> SqlOperation:
    source = raw["source"]
    return SqlOperation(
        operation_type=raw["operation_type"],
        module=_module(raw["module"]),
        sequence=raw["sequence"],
        branch_path=tuple(raw["branch_path"]),
        conditions=tuple(raw["conditions"]),
        where=raw["where"],
        read_tables=_references(raw["read_tables"]),
        write_tables=_references(raw["write_tables"]),
        unresolved_write_targets=tuple(raw["unresolved_write_targets"]),
        read_columns=tuple(raw["read_columns"]),
        written_columns=tuple(raw["written_columns"]),
        function_references=_references(raw["function_references"]),
        call_targets=_references(raw["call_targets"]),
        dynamic_sql=raw["dynamic_sql"],
        source=SqlSourceLocation(
            start_line=source["start_line"],
            start_column=source["start_column"],
            start_offset=source["start_offset"],
            length=source["length"],
            end_line=source["end_line"],
            end_column=source["end_column"],
        ),
    )


def _module(raw: dict[str, Any]) -> SqlModuleIdentity:
    if raw["type"] == "unknown":
        # The host names a text outside a module after its input file. That
        # name is a temporary file name, so it stops here.
        return SqlModuleIdentity()
    return SqlModuleIdentity(type=raw["type"], schema=raw["schema"], name=raw["name"])


def _references(raw: list[dict[str, str]]) -> tuple[ObjectName, ...]:
    """Read each analyzer reference; the host always reports all four parts."""
    return tuple(
        ObjectName(
            server=entry["server"],
            database=entry["database"],
            schema=entry["schema"],
            name=entry["name"],
        )
        for entry in raw
    )
