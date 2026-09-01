from __future__ import annotations

from types import SimpleNamespace

from app.db.alembic_hooks import include_registry_object


def reflected_object(table_name: str) -> SimpleNamespace:
    return SimpleNamespace(table=SimpleNamespace(name=table_name))


def test_only_exact_migration_managed_postgis_objects_are_excluded() -> None:
    camera_object = reflected_object("cameras")
    assert include_registry_object(camera_object, "location_geog", "column", True, None) is False
    assert (
        include_registry_object(camera_object, "ix_cameras_location_geog", "index", True, None)
        is False
    )

    assert include_registry_object(camera_object, "longitude", "column", True, None)
    assert include_registry_object(camera_object, "ix_cameras_health", "index", True, None)
    assert include_registry_object(
        reflected_object("other_table"), "location_geog", "column", True, None
    )
    assert include_registry_object(camera_object, "location_geog", "column", False, None)
    assert include_registry_object(camera_object, "location_geog", "column", True, object())
