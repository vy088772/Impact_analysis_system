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

A `Web.config` table also holds the entries of each Parent Application of the
web application, nearest first (ADR-0038). The chain starts from the project
file beside the `Web.config` that supplied the table. The own entry of the
application wins over an inherited entry. Each namespace inherits only from the
same namespace. A `<clear/>` or a `<remove>` in a `Web.config` stops the
inheritance from above it, and a section in a `<location>` that has
`inheritInChildApplications="false"` does not pass to child applications. After
the inheritance, rule 6 gives the guess only when the own table and each
inherited table are empty.

Rules 3 to 5 extend ADR-0018: a `Web.config` table also covers one Project
Connection Scope, and a project with no configuration file uses the
`Web.config` of the scan root. The amendment of ADR-0018 records these rules.

The two configuration parsers stay pure parsers. This module reads no user
name and no password (ADR-0010), because the parsers give none.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple, Union

from .clone_root import find_clone_root
from .connection_string_value import ResolvedConnection
from .parent_application import ParentApplications
from .project_connection_scope import (
    BASE_SETTINGS_FILE_NAME,
    CONNECTION_KEY_NOT_IN_PROJECT_SCOPE,
    CONTEXT_TYPE_NOT_REGISTERED,
    IGNORED_DIRECTORY_NAMES,
    NO_PROJECT_CONNECTION_SCOPE,
    PROJECT_FILE_SUFFIXES,
    ROOT_CONFIGURATION_NAMESPACE,
    ProjectConnectionScope,
    build_project_connection_scope,
)
from .webconfig_connection_resolver import (
    EntryBlocks,
    WebConfigConnections,
    parse_web_config_file,
)

# The namespaces of a lookup key. ADR-0008 keeps them apart.
APP_SETTINGS = "app_settings"
CONNECTION_STRINGS = "connection_strings"
# The Configuration Root Namespace is not a connection lookup table. A key in
# this namespace never resolves.
ROOT_CONFIGURATION = "root_configuration"

WEB_CONFIG_FILE_NAME = "web.config"

LookupTable = Mapping[str, ResolvedConnection]


@dataclass(frozen=True)
class TableLayer:
    """The two lookup tables of one configuration file, and the file that declared them.

    `declared_in` is a path relative to the clone root, or to the scan root
    when the analyzer finds no clone root. `blocks` holds, for each namespace,
    what the file stops from above: a `<clear/>` or a `<remove>`.
    """

    tables: Mapping[str, LookupTable]
    declared_in: str
    blocks: Mapping[str, EntryBlocks] = field(default_factory=dict)

    def stops(self, namespace: str, key: str) -> bool:
        """True when this file keeps a key of the layers above it from the application."""
        blocks = self.blocks.get(namespace)
        return blocks is not None and blocks.stops(key)


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

    `layers` holds the own table of the source file first, then the table of
    each Parent Application, nearest first. The first layer that declares a key
    in a namespace answers it. A layer that clears the namespace, or removes the
    key, ends the search.
    """

    def __init__(
        self,
        *,
        layers: Optional[Sequence[TableLayer]] = None,
        reads_application_settings_file: bool = False,
        no_table_reason: str = "",
        context_lookup_keys: Optional[Mapping[str, str]] = None,
        root_configuration_keys: FrozenSet[str] = frozenset(),
        root_connection_keys: FrozenSet[str] = frozenset(),
    ):
        self._layers = layers
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
        if self._layers is None:
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
        for layer in self._layers or ():
            resolved = _find_key(layer.tables.get(namespace, {}), key)
            if resolved is not None:
                return ConnectionAnswer(
                    database=resolved.database,
                    server=resolved.server,
                    declared_in=layer.declared_in,
                )
            if layer.stops(namespace, key):
                break
        return None

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
        connection_strings = {
            name: value
            for layer in self._layers or ()
            for name, value in layer.tables.get(CONNECTION_STRINGS, {}).items()
        }
        folded = key.casefold()
        return any(
            name.casefold() == folded
            for name in (*self._root_connection_keys, *connection_strings)
        )


class ConnectionLookup:
    """The connection lookup tables of one scan root."""

    def __init__(self, scan_root: Union[str, Path]):
        self._scan_root = Path(scan_root).resolve()
        self._clone_root = find_clone_root(self._scan_root)
        # Declaring files are relative to the clone root when one exists.
        self._path_base = self._clone_root or self._scan_root
        self._parent_applications = ParentApplications(self._clone_root)
        self._parsed_web_configs: Dict[Path, WebConfigConnections] = {}
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
            layers=[
                TableLayer(
                    tables={CONNECTION_STRINGS: scope.connection_strings},
                    declared_in=self._relative_path(Path(str(scope.settings_file))),
                )
            ],
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
        """The view of one `Web.config` table and the tables it inherits.

        The layers are the own `Web.config` first, then the `Web.config` of
        each Parent Application, nearest first. A layer that is empty in the
        two namespaces and stops nothing does not count. When no layer holds an
        entry, or no `Web.config` exists, the view gives the key-as-name guess.
        """
        if web_config is None:
            return FileConnections()
        layers = []
        for position, path in enumerate([web_config, *self._parent_web_configs(web_config)]):
            parsed = self._parse_web_config(path)
            # The own layer serves its own application, so it also holds the
            # sections that a `<location>` keeps from child applications.
            own = position == 0
            layer = TableLayer(
                tables={
                    APP_SETTINGS: {
                        **parsed.app_settings,
                        **(parsed.own_only_app_settings if own else {}),
                    },
                    CONNECTION_STRINGS: {
                        **parsed.connection_strings,
                        **(parsed.own_only_connection_strings if own else {}),
                    },
                },
                declared_in=self._relative_path(path),
                blocks={
                    APP_SETTINGS: parsed.app_settings_blocks,
                    CONNECTION_STRINGS: parsed.connection_strings_blocks,
                },
            )
            if any(layer.tables.values()) or parsed.blocks_inheritance:
                layers.append(layer)
        if not any(any(layer.tables.values()) for layer in layers):
            return FileConnections()
        return FileConnections(layers=layers)

    def _parent_web_configs(self, web_config: Path) -> List[Path]:
        """The `Web.config` of each Parent Application, nearest first.

        The chain starts from the project file beside the `Web.config` that
        supplied the table. An ancestor with no `Web.config` adds no layer, and
        the chain goes on above it. The analyzer reads the project file and the
        `Web.config` of an ancestor, and no code.
        """
        project_file = self._project_file_beside(web_config.parent)
        if project_file is None:
            return []
        found = (
            _find_file(parent.parent, WEB_CONFIG_FILE_NAME)
            for parent in self._parent_applications.chain_of(project_file)
        )
        return [path for path in found if path is not None]

    def _parse_web_config(self, web_config: Path) -> WebConfigConnections:
        if web_config not in self._parsed_web_configs:
            try:
                parsed = parse_web_config_file(web_config)
            except (OSError, UnicodeDecodeError) as error:
                # This module reads the `Web.config` of each project, so one file
                # that is not readable must not stop the scan.
                print(f"⚠️ The analyzer cannot read {web_config}: {error}")
                parsed = WebConfigConnections()
            self._parsed_web_configs[web_config] = parsed
        return self._parsed_web_configs[web_config]

    def _scan_root_holds_application_settings_file(self) -> bool:
        """True when an Application Settings File is in or below the scan root.

        The search does not go into a directory that holds build output or
        packages.
        """
        if self._holds_application_settings_file is None:
            self._holds_application_settings_file = False
            folded_name = BASE_SETTINGS_FILE_NAME.casefold()
            for _, directory_names, file_names in os.walk(self._scan_root):
                directory_names[:] = [
                    name
                    for name in directory_names
                    if name.casefold() not in IGNORED_DIRECTORY_NAMES
                ]
                if any(name.casefold() == folded_name for name in file_names):
                    self._holds_application_settings_file = True
                    break
        return self._holds_application_settings_file

    def _relative_path(self, path: Path) -> str:
        """A declaring file as a path relative to the clone root.

        The base is the scan root when the analyzer finds no clone root.
        """
        return Path(os.path.relpath(path, self._path_base)).as_posix()

    @staticmethod
    def _project_file_beside(directory: Path) -> Optional[Path]:
        try:
            project_files = sorted(
                found
                for suffix in PROJECT_FILE_SUFFIXES
                for found in directory.glob(f"*{suffix}")
            )
        except OSError:
            return None
        return project_files[0] if project_files else None

    def _project_file_for(self, source_file: Union[str, Path]) -> Optional[Path]:
        """The nearest project file above a source file.

        The search stops at the clone root. When the analyzer finds no clone
        root, the search has no upper bound. One scan asks this question for
        thousands of source files that share their parent directories, so each
        directory is examined one time.
        """
        path = Path(source_file).resolve()
        directory = path if path.is_dir() else path.parent
        candidates = [directory, *directory.parents]
        if self._clone_root in candidates:
            candidates = candidates[: candidates.index(self._clone_root) + 1]
        unknown: List[Path] = []
        answer: Optional[Path] = None
        for candidate in candidates:
            if candidate in self._project_files:
                answer = self._project_files[candidate]
                break
            unknown.append(candidate)
            found = self._project_file_beside(candidate)
            if found is not None:
                answer = found
                break
        for candidate in unknown:
            self._project_files[candidate] = answer
        return answer
