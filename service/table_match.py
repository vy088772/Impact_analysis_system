"""The table match: does one target in the graph answer a table question?

One rule serves every site that compares a target with the table a caller
names: the Execution Path match, the lineage of a View or a Function, and the
inline C# SQL match. It composes its keys with the Canonical Object Identity
module and never fills an unstated schema with `dbo`.

- The question takes the Database of the request when its name states none.
- A target that states another Database never matches. A side that states no
  Database is not compared, so an unknown Database over-reports.
- A question that states no schema matches every target with that bare name.
- A question that states a schema matches a target that states the same schema.
  A target that states another schema never matches.
- A target that states no schema matches too, through the bare key. That match
  carries the Unproven Schema mark. The mark describes the target, never the
  question.
- A match carries the schema source of its target: how the schema was found.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import schema_resolution
from canonical_object_identity import ObjectName, bare_key, parse, part_key

UNPROVEN_SCHEMA = "unproven_schema"


def names_another_database(database: Optional[str], own_database: Optional[str]) -> bool:
    """Whether a reference states a Database, and that Database is not the cache's own."""
    return bool(part_key(database)) and part_key(database) != part_key(own_database)


def names_listed_node(node: Mapping[str, Any], schema: Optional[str], name: Optional[str]) -> bool:
    """The two-bucket rule over one listed node, whose schema is always stated.

    A reference that states a schema names the node of that schema. A reference
    that states no schema names every node with the bare name.
    """
    return bare_key(str(node.get("name") or "")) == bare_key(name) and (
        not part_key(schema) or part_key(str(node.get("schema") or "")) == part_key(schema)
    )


@dataclass(frozen=True)
class TableMatch:
    """One match: the mark of the target, and the Database it names when that is not the cache's own."""

    unproven_schema: bool
    stated_database: Optional[str]
    schema_source: str = ""


@dataclass(frozen=True)
class TableQuestion:
    """The table a caller names, in three keys: database, schema, and bare name."""

    database: str
    schema: str
    name: str

    @classmethod
    def of(cls, table_name: str, request_database: str = "") -> "TableQuestion":
        written = parse(table_name)
        return cls(
            database=part_key(written.database) or part_key(request_database),
            schema=part_key(written.schema),
            name=bare_key(written),
        )

    def match(
        self, target: ObjectName, own_database: Optional[str], schema_source: str = ""
    ) -> Optional[TableMatch]:
        """Return the match of one target, or None when the target does not answer.

        ``own_database`` is the Database of the cache, or of the C# connection,
        that holds the target. A target that states no Database takes it. A
        target that names another Database reports it as ``stated_database``,
        in the case the source wrote it. ``schema_source`` states how the graph
        or the caller found the schema of the target. An empty value reads as
        ``written`` for a target that states a schema, else ``unresolved``.
        """
        if not self.name or bare_key(target) != self.name:
            return None
        database = target.database or own_database
        target_database = part_key(database)
        if self.database and target_database and self.database != target_database:
            return None
        target_schema = part_key(target.schema)
        if self.schema and target_schema and self.schema != target_schema:
            return None
        # A connection or cache with no known Database states no other Database.
        stated = bool(part_key(own_database)) and names_another_database(database, own_database)
        return TableMatch(
            unproven_schema=not target_schema,
            stated_database=str(database) if stated else None,
            schema_source=schema_source
            or (schema_resolution.WRITTEN if target_schema else schema_resolution.UNRESOLVED),
        )
