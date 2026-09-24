"""Canonical Object Identity: the rule that turns a written SQL object name into a comparison key.

A written name has up to four dotted parts: server, database, schema, and bare
name. The parse reads them from the right, so `Orders` states only a bare name
and `srv.PUR.dbo.Users` states all four. Brackets and the whitespace around
each part are dropped.

An empty field means "not stated", never "default". The parse never fills an
unstated schema with `dbo`, and it takes no default-schema argument.

Two keys compare names:

- The bare key is the casefolded bare name.
- The full key is `database.schema.name`, casefolded. It always holds three
  segments, so an empty part stays an empty segment: `Orders` gives `..orders`.

No key reads the server field. The field only keeps a four-part name's server.

This module imports nothing from this project, so every package can import it.
The mirror module in `llamaindex-spec-rag` follows the same rule, and both pass
the `object_names` list in `tests/cross_repository_agreement.json`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union


@dataclass(frozen=True)
class ObjectName:
    """One written SQL object name, split into its four parts in their written case."""

    server: str
    database: str
    schema: str
    name: str


def parse(written: Optional[str]) -> ObjectName:
    """Split a written name into its parts; a part the name does not state stays empty."""
    parts = [part.strip() for part in (written or "").replace("[", "").replace("]", "").split(".")]
    parts = [""] * (4 - len(parts)) + parts[-4:]
    server, database, schema, name = parts
    return ObjectName(server=server, database=database, schema=schema, name=name)


def bare_name(name: Union[ObjectName, str, None]) -> str:
    """Return the bare name in its written case, for a caller that builds a pattern from it."""
    return _parsed(name).name


def bare_key(name: Union[ObjectName, str, None]) -> str:
    """Return the key that ignores the database and the schema."""
    return _parsed(name).name.casefold()


def full_key(name: Union[ObjectName, str, None]) -> str:
    """Return the `database.schema.name` key; an unstated part stays an empty segment."""
    parsed = _parsed(name)
    return ".".join(part.casefold() for part in (parsed.database, parsed.schema, parsed.name))


def _parsed(name: Union[ObjectName, str, None]) -> ObjectName:
    return name if isinstance(name, ObjectName) else parse(name)
