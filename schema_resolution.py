"""Schema Resolution: the schema SQL Server gives a name that states none.

SQL Server looks for an unqualified name in the active default schema, then in
`dbo`. Inside a procedure, a view, or a function, the active default schema is
the module's own schema. Everywhere else it is the login's default schema, and
every login in this shop has the default schema `dbo`.

The rule reads the cache's object listing. One schema holds one namespace for
tables, views, procedures, and functions, so the lookup crosses object kinds.

A name that the listing holds in neither schema keeps an empty schema: a temp
table, an object of another Database, and a broken reference are not guessed. A
`db..name` reference keeps an empty schema too. In the other Database, SQL
Server uses the default schema of the module schema owner. That is `dbo` in this
shop, but this rule reads no listing of that Database, so nothing proves it.

Each result records its schema source, so a reader can tell a written schema
from a resolved one.

This module imports nothing from this project except the Canonical Object
Identity module, so every package can import it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Callable, Optional

from canonical_object_identity import ObjectName

# The login default schema of this shop. No per-Database or per-System setting exists.
DEFAULT_SCHEMA = "dbo"
# The schema of the system procedures. The listing holds no `sys` object.
SYSTEM_SCHEMA = "sys"
_SYSTEM_PREFIXES = ("sp_", "xp_")


class SchemaSource(StrEnum):
    """How the schema of a reference was found, strongest first.

    A member is the text that a relationship and a table match record hold.
    """

    WRITTEN = "written"
    MODULE_SCHEMA = "module_schema"
    DEFAULT_SCHEMA = "default_schema"
    SYSTEM = "system"
    UNRESOLVED = "unresolved"


_STRENGTH_ORDER = tuple(SchemaSource)


def recorded_source(schema_source: Optional[str], schema: Optional[str]) -> str:
    """Return the schema source that one record states.

    A record that states none reads as ``written`` when its target states a
    schema, else ``unresolved``. A hand-written graph and a target that no rule
    resolved are the two cases.
    """
    return str(schema_source or (SchemaSource.WRITTEN if schema else SchemaSource.UNRESOLVED))


def strongest_source(kept: str, other: str) -> str:
    """Return the stronger of two schema sources; a tie keeps the first.

    A fact that two references prove keeps the strongest source. A value that
    the rule does not know is the weakest.
    """
    return min(kept, other, key=_strength_position)


def _strength_position(schema_source: str) -> int:
    if schema_source in _STRENGTH_ORDER:
        return _STRENGTH_ORDER.index(schema_source)
    return len(_STRENGTH_ORDER)


def resolve(
    reference: ObjectName,
    module_schema: str,
    holds: Callable[[str, str], bool],
) -> tuple[str, SchemaSource]:
    """Return the schema of ``reference`` and its schema source.

    ``module_schema`` is the schema of the module that holds the reference, or
    an empty string outside a module. ``holds(schema, name)`` answers whether the
    listing holds that object, of any kind.
    """
    if reference.schema:
        return reference.schema, SchemaSource.WRITTEN
    if reference.database:
        return "", SchemaSource.UNRESOLVED
    if module_schema and holds(module_schema, reference.name):
        return module_schema, SchemaSource.MODULE_SCHEMA
    if holds(DEFAULT_SCHEMA, reference.name):
        return DEFAULT_SCHEMA, SchemaSource.DEFAULT_SCHEMA
    return "", SchemaSource.UNRESOLVED


def resolve_call(
    reference: ObjectName,
    module_schema: str,
    holds: Callable[[str, str], bool],
) -> tuple[str, SchemaSource]:
    """Return the schema of a procedure call and its schema source.

    A call follows ``resolve()``. An unqualified ``sp_`` or ``xp_`` name that the
    listing holds in neither schema is a system procedure, so it resolves to
    ``sys``. SQL Server checks ``sys`` first, but the listing holds no ``sys``
    object, so a listed user procedure with that prefix still wins.
    """
    schema, source = resolve(reference, module_schema, holds)
    if (
        source == SchemaSource.UNRESOLVED
        and not reference.database
        and reference.name.casefold().startswith(_SYSTEM_PREFIXES)
    ):
        return SYSTEM_SCHEMA, SchemaSource.SYSTEM
    return schema, source
