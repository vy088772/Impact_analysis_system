# code_analyzer/connection_lookup.py
"""The Connection Lookup: which connection a lookup key opens for one source file.

The analyzer makes one Connection Lookup for one scan root. The Connection
Lookup gives one view for each source file. The view answers a lookup key in
one namespace. This module is the only place that selects a connection lookup
table for a source file.

The view selects a table by these rules, in this order:

1. A source file belongs to the nearest project file above it.
2. If an Application Settings File is beside that project file, the view uses
   it. It wins when a `Web.config` is also there.
3. If not, the view uses the `Web.config` beside that project file.
4. If the project has neither file, the view uses the `Web.config` of the scan
   root.
5. A source file with no project file above it also uses the `Web.config` of
   the scan root. When the scan root holds an Application Settings File, that
   source file has no table, and each answer holds the reason
   `no_project_connection_scope`.
6. When the selected `Web.config` table is empty in the two namespaces, or no
   `Web.config` exists, the view gives the key-as-name guess.

Rules 3 to 5 extend ADR-0018: a `Web.config` table also covers one Project
Connection Scope, and a project with no configuration file uses the
`Web.config` of the scan root. The ADR gains that amendment when the project
scanner starts to use this module.

The two configuration parsers stay pure parsers. This module reads no user
name and no password (ADR-0010), because the parsers give none.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Tuple, Union

from .connection_string_value import ResolvedConnection
from .project_connection_scope import (
    CONNECTION_KEY_NOT_IN_PROJECT_SCOPE,
    CONTEXT_TYPE_NOT_REGISTERED,
    NO_PROJECT_CONNECTION_SCOPE,
    PROJECT_FILE_SUFFIXES,
    ROOT_CONFIGURATION_NAMESPACE,
    ProjectConnectionScope,
    ProjectConnectionScopeIndex,
    build_project_connection_scope,
)
from .webconfig_connection_resolver import parse_web_config_file

# The namespaces of a lookup key. ADR-0008 keeps them apart.
APP_SETTINGS = "app_settings"
CONNECTION_STRINGS = "connection_strings"
# The Configuration Root Namespace is not a connection lookup table. A key in
# this namespace never resolves.
ROOT_CONFIGURATION = "root_configuration"

WEB_CONFIG_FILE_NAME = "web.config"

LookupTable = Mapping[str, ResolvedConnection]


@dataclass(frozen=True)
class ConnectionAnswer:
    """The answer of a view for one lookup key in one namespace.

    `declared_in` names the configuration file that declared the key, as a
    path relative to the scan root. `reason` states why the lookup failed. One
    answer holds all four fields, so a caller cannot lose the reason.
    """

    database: Optional[str] = None
    server: Optional[str] = None
    declared_in: Optional[str] = None
    reason: str = ""


@dataclass(frozen=True)
class ContextRegistration:
    """The Context Connection Registration of one context type.

    `lookup_key` is the lookup key that the composition root registers for the
    context type. `reason` states why the view knows no registration. The two
    fields are empty on the `Web.config` path.
    """

    lookup_key: str = ""
    reason: str = ""


def _find_file(directory: Path, folded_name: str) -> Optional[Path]:
    """The file in a directory whose name agrees with no regard to case."""
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return None
    for entry in entries:
        if entry.name.casefold() == folded_name and entry.is_file():
            return entry
    return None


def _find_key(table: LookupTable, key: str) -> Optional[ResolvedConnection]:
    """The entry of a lookup key in one table, with no regard to case."""
    resolved = table.get(key)
    if resolved is None:
        folded = key.casefold()
        resolved = next(
            (value for name, value in table.items() if name.casefold() == folded),
            None,
        )
    return resolved if resolved is not None and resolved.database else None


class FileConnections:
    """The view of the Connection Lookup for one source file.

    A view with no table and no reason gives the key-as-name guess: the lookup
    key as the Database, no server, and no declaring file.
    """

    def __init__(
        self,
        *,
        tables: Optional[Mapping[str, LookupTable]] = None,
        declared_in: Optional[str] = None,
        reads_application_settings_file: bool = False,
        no_table_reason: str = "",
        context_lookup_keys: Optional[Mapping[str, str]] = None,
        root_configuration_keys: FrozenSet[str] = frozenset(),
        root_connection_keys: FrozenSet[str] = frozenset(),
    ):
        self._tables = tables
        self._declared_in = declared_in
        self._reads_application_settings_file = reads_application_settings_file
        self._no_table_reason = no_table_reason
        self._context_lookup_keys = dict(context_lookup_keys or {})
        self._root_configuration_keys = root_configuration_keys
        self._root_connection_keys = root_connection_keys

    @property
    def reads_application_settings_file(self) -> bool:
        """True when the source file is on the Application Settings File path.

        This is also true for a source file that has no table because the scan
        root holds an Application Settings File.
        """
        return self._reads_application_settings_file

    @property
    def registered_context_types(self) -> Tuple[str, ...]:
        """The context types that have a Context Connection Registration, in name order."""
        return tuple(sorted(self._context_lookup_keys))

    def lookup(self, key: str, namespace: str) -> ConnectionAnswer:
        """The connection that a lookup key opens in one namespace."""
        if self._no_table_reason:
            return ConnectionAnswer(reason=self._no_table_reason)
        if self._tables is None:
            return ConnectionAnswer(database=key)
        if not self._reads_application_settings_file:
            # A failed lookup on the `Web.config` path has no reason.
            return self._answer_from_table(key, namespace) or ConnectionAnswer()
        if namespace == ROOT_CONFIGURATION:
            return ConnectionAnswer(reason=ROOT_CONFIGURATION_NAMESPACE)
        return self._answer_from_table(key, namespace) or ConnectionAnswer(
            reason=(
                ROOT_CONFIGURATION_NAMESPACE
                if key in self._root_configuration_keys
                else CONNECTION_KEY_NOT_IN_PROJECT_SCOPE
            )
        )

    def _answer_from_table(self, key: str, namespace: str) -> Optional[ConnectionAnswer]:
        resolved = _find_key((self._tables or {}).get(namespace, {}), key)
        if resolved is None:
            return None
        return ConnectionAnswer(
            database=resolved.database,
            server=resolved.server,
            declared_in=self._declared_in,
        )

    def context_registration(self, context_type: str) -> ContextRegistration:
        """The Context Connection Registration of a context type."""
        if self._no_table_reason:
            return ContextRegistration(reason=self._no_table_reason)
        if not self._reads_application_settings_file:
            return ContextRegistration()
        lookup_key = self._context_lookup_keys.get(context_type)
        if not lookup_key:
            return ContextRegistration(reason=CONTEXT_TYPE_NOT_REGISTERED)
        return ContextRegistration(lookup_key=lookup_key)

    def names_a_connection(self, key: str) -> bool:
        """True when a Configuration Root Namespace key names a connection.

        The key names a connection when the `ConnectionStrings` section holds
        the same name, or when the value of the key is a connection string.
        The answer is always false on the `Web.config` path.
        """
        if not self._reads_application_settings_file:
            return False
        connection_strings = (self._tables or {}).get(CONNECTION_STRINGS, {})
        folded = key.casefold()
        return any(
            name.casefold() == folded
            for name in (*self._root_connection_keys, *connection_strings)
        )


class ConnectionLookup:
    """The connection lookup tables of one scan root."""

    def __init__(self, scan_root: Union[str, Path]):
        self._scan_root = Path(scan_root).resolve()
        self._project_files: Dict[Path, Optional[Path]] = {}
        self._project_views: Dict[Path, FileConnections] = {}
        self._environment_overrides: Dict[Tuple[str, str], Dict[str, object]] = {}
        self._scan_root_view: Optional[FileConnections] = None
        self._holds_application_settings_file: Optional[bool] = None

    def for_file(self, source_file: Union[str, Path]) -> FileConnections:
        """The view of one source file."""
        project_file = self._project_file_for(source_file)
        if project_file is None:
            if self._scan_root_holds_application_settings_file():
                return FileConnections(
                    reads_application_settings_file=True,
                    no_table_reason=NO_PROJECT_CONNECTION_SCOPE,
                )
            return self._view_of_scan_root()
        if project_file not in self._project_views:
            self._project_views[project_file] = self._view_of_project(project_file)
        return self._project_views[project_file]

    def environment_overrides(self) -> List[Dict[str, object]]:
        """Each Environment Settings Override of the projects examined so far.

        The list has one entry for each settings file and lookup key, in that
        order.
        """
        return [self._environment_overrides[key] for key in sorted(self._environment_overrides)]

    def _view_of_project(self, project_file: Path) -> FileConnections:
        scope = build_project_connection_scope(project_file)
        if scope is not None:
            return self._application_settings_view(scope)
        web_config = _find_file(project_file.parent, WEB_CONFIG_FILE_NAME)
        if web_config is not None:
            return self._web_config_view(web_config)
        return self._view_of_scan_root()

    def _application_settings_view(self, scope: ProjectConnectionScope) -> FileConnections:
        for override in scope.environment_overrides:
            self._environment_overrides[
                (override.settings_file, override.lookup_key)
            ] = override.to_dict()
        return FileConnections(
            tables={CONNECTION_STRINGS: scope.connection_strings},
            declared_in=self._relative_to_scan_root(Path(str(scope.settings_file))),
            reads_application_settings_file=True,
            context_lookup_keys=scope.context_connection_keys,
            root_configuration_keys=scope.root_configuration_keys,
            root_connection_keys=scope.root_connection_keys,
        )

    def _view_of_scan_root(self) -> FileConnections:
        if self._scan_root_view is None:
            self._scan_root_view = self._web_config_view(self._scan_root_web_config())
        return self._scan_root_view

    def _scan_root_web_config(self) -> Optional[Path]:
        """The `Web.config` of the scan root.

        The search looks in the scan root directory first. It then looks in
        each first-level directory, in name order.
        """
        found = _find_file(self._scan_root, WEB_CONFIG_FILE_NAME)
        if found is not None:
            return found
        try:
            entries = sorted(self._scan_root.iterdir())
        except OSError:
            return None
        for entry in entries:
            if entry.is_dir():
                found = _find_file(entry, WEB_CONFIG_FILE_NAME)
                if found is not None:
                    return found
        return None

    def _web_config_view(self, web_config: Optional[Path]) -> FileConnections:
        """The view of one `Web.config` table.

        When the table is empty in the two namespaces, or no `Web.config`
        exists, the view gives the key-as-name guess.
        """
        if web_config is None:
            return FileConnections()
        try:
            parsed = parse_web_config_file(web_config)
        except (OSError, UnicodeDecodeError) as error:
            # This module reads the `Web.config` of each project, so one file
            # that is not readable must not stop the scan.
            print(f"⚠️ The analyzer cannot read {web_config}: {error}")
            return FileConnections()
        if not parsed:
            return FileConnections()
        return FileConnections(
            tables={
                APP_SETTINGS: parsed.app_settings,
                CONNECTION_STRINGS: parsed.connection_strings,
            },
            declared_in=self._relative_to_scan_root(web_config),
        )

    def _scan_root_holds_application_settings_file(self) -> bool:
        if self._holds_application_settings_file is None:
            self._holds_application_settings_file = ProjectConnectionScopeIndex(
                self._scan_root
            ).enabled
        return self._holds_application_settings_file

    def _relative_to_scan_root(self, path: Path) -> str:
        return Path(os.path.relpath(path, self._scan_root)).as_posix()

    def _project_file_for(self, source_file: Union[str, Path]) -> Optional[Path]:
        """The nearest project file above a source file.

        The search has no upper bound. One scan asks this question for
        thousands of source files that share their parent directories, so each
        directory is examined one time.
        """
        path = Path(source_file).resolve()
        directory = path if path.is_dir() else path.parent
        unknown: List[Path] = []
        answer: Optional[Path] = None
        for candidate in [directory, *directory.parents]:
            if candidate in self._project_files:
                answer = self._project_files[candidate]
                break
            unknown.append(candidate)
            try:
                project_files = sorted(
                    found
                    for suffix in PROJECT_FILE_SUFFIXES
                    for found in candidate.glob(f"*{suffix}")
                )
            except OSError:
                continue
            if project_files:
                answer = project_files[0]
                break
        for candidate in unknown:
            self._project_files[candidate] = answer
        return answer
