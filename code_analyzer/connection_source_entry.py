# code_analyzer/connection_source_entry.py
"""The two shapes of a connection source entry.

A connection source entry is the value that the C# Scan Result holds for one
connection variable of one source file. It has two shapes. A Resolved
Connection Source is a mapping with a database and a server. A Legacy
Connection Label is a bare string that an older scan wrote.

One C# Scan Result can hold the two shapes together, because a refresh rescans
only the files that changed. This module is the only place that knows the two
shapes. A reader of an entry calls these functions and never examines the
shape.
"""

from __future__ import annotations

from typing import Mapping, Optional, TypedDict, Union, cast


class ResolvedConnectionSource(TypedDict):
    """The fields of the stored mapping that this module knows.

    The run-time value is a plain dict. A stored mapping can hold a field that
    this description does not list. `with_database` keeps each such field.
    """

    database: str
    server: Optional[str]


ConnectionSourceEntry = Union[ResolvedConnectionSource, str]


def database_of(entry: Optional[ConnectionSourceEntry]) -> str:
    """The Database name of an entry, with no space at each end.

    Gives empty text when the entry has no Database, or when there is no entry.
    """
    value = entry.get("database") if isinstance(entry, Mapping) else entry
    return str(value or "").strip()


def server_of(entry: Optional[ConnectionSourceEntry]) -> Optional[str]:
    """The server of an entry, with no space at each end.

    Gives None when the server is absent or blank. A Legacy Connection Label
    has no server.
    """
    if not isinstance(entry, Mapping):
        return None
    return str(entry.get("server") or "").strip() or None


def has_resolved_shape(entry: ConnectionSourceEntry) -> bool:
    """True when the entry is a mapping, false when it is a bare string.

    This examines the shape only. A key-as-name guess also has the mapping
    shape, so a true result does not prove that a configuration file declares
    the Database.
    """
    return isinstance(entry, Mapping)


def with_database(entry: ConnectionSourceEntry, database: str) -> ConnectionSourceEntry:
    """An entry of the same shape for another Database.

    For a mapping, copies each field and replaces only the Database, so the
    server and each field that this module does not know stay. For a Legacy
    Connection Label, gives the new Database name as a bare string.
    """
    if isinstance(entry, Mapping):
        # The cast is necessary because the copy can hold a field that the
        # typed description does not list.
        return cast(ResolvedConnectionSource, {**entry, "database": database})
    return database


def resolved_entry(database: str, server: Optional[str]) -> ResolvedConnectionSource:
    """The stored form of a Resolved Connection Source."""
    return {"database": database, "server": server}
