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

from typing import Callable

from canonical_object_identity import ObjectName

# The login default schema of this shop. No per-Database or per-System setting exists.
DEFAULT_SCHEMA = "dbo"
# The schema of the system procedures. The listing holds no `sys` object.
SYSTEM_SCHEMA = "sys"
_SYSTEM_PREFIXES = ("sp_", "xp_")

WRITTEN = "written"
MODULE_SCHEMA = "module_schema"
DEFAULT_SCHEMA_SOURCE = "default_schema"
SYSTEM = "system"
UNRESOLVED = "unresolved"

# Strongest first. A fact that two references prove keeps the strongest source.
SOURCES = (WRITTEN, MODULE_SCHEMA, DEFAULT_SCHEMA_SOURCE, SYSTEM, UNRESOLVED)


def resolve(
    reference: ObjectName,
    module_schema: str,
    holds: Callable[[str, str], bool],
) -> tuple[str, str]:
    """Return the schema of ``reference`` and its schema source.

    ``module_schema`` is the schema of the module that holds the reference, or
    an empty string outside a module. ``holds(schema, name)`` answers whether the
    listing holds that object, of any kind.
    """
    if reference.schema:
        return reference.schema, WRITTEN
    if reference.database:
        return "", UNRESOLVED
    if module_schema and holds(module_schema, reference.name):
        return module_schema, MODULE_SCHEMA
    if holds(DEFAULT_SCHEMA, reference.name):
        return DEFAULT_SCHEMA, DEFAULT_SCHEMA_SOURCE
    return "", UNRESOLVED


def resolve_call(
    reference: ObjectName,
    module_schema: str,
    holds: Callable[[str, str], bool],
) -> tuple[str, str]:
    """Return the schema of a procedure call and its schema source.

    A call follows ``resolve()``. An unqualified ``sp_`` or ``xp_`` name that the
    listing holds in neither schema is a system procedure, so it resolves to
    ``sys``. SQL Server checks ``sys`` first, but the listing holds no ``sys``
    object, so a listed user procedure with that prefix still wins.
    """
    schema, source = resolve(reference, module_schema, holds)
    if (
        source == UNRESOLVED
        and not reference.database
        and reference.name.casefold().startswith(_SYSTEM_PREFIXES)
    ):
        return SYSTEM_SCHEMA, SYSTEM
    return schema, source
