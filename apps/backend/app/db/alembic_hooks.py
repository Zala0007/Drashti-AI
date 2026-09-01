from __future__ import annotations

from typing import Any


def include_registry_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Keep migration-managed PostGIS artifacts out of autogenerate drift.

    ``location_geog`` is a generated geography column and its GiST index is
    intentionally created with raw PostGIS DDL in the initial migration. They
    cannot be represented by the dependency-light SQLAlchemy registry model.
    Only these exact reflected, database-only objects are excluded. Every other
    column, index, constraint and table remains subject to Alembic comparison.
    """

    if not reflected or compare_to is not None:
        return True
    table = getattr(object_, "table", None)
    table_name = getattr(table, "name", None)
    if type_ == "column" and table_name == "cameras" and name == "location_geog":
        return False
    return not (type_ == "index" and table_name == "cameras" and name == "ix_cameras_location_geog")
