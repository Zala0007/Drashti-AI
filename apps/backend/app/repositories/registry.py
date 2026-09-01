from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.models import AuditLog, Camera, Department, ImportJob


@dataclass(slots=True)
class CameraFilters:
    search: str | None = None
    department_id: str | None = None
    district: str | None = None
    city: str | None = None
    vendor: str | None = None
    vms: str | None = None
    camera_type: str | None = None
    status: str | None = None
    health: str | None = None
    connectivity_type: str | None = None
    stream_protocol: str | None = None
    ai_capability: str | None = None
    ai_enabled: bool | None = None
    tag: str | None = None
    include_retired: bool = False
    bbox: tuple[float, float, float, float] | None = None
    near_lat: float | None = None
    near_lon: float | None = None
    radius_m: float | None = None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_008.8
    phi_1 = math.radians(lat1)
    phi_2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_1) * math.cos(phi_2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * earth_radius_m * math.asin(math.sqrt(haversine))


class RegistryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @property
    def dialect(self) -> str:
        bind = self.session.get_bind()
        return bind.dialect.name

    def add(self, entity: Any) -> None:
        self.session.add(entity)

    def get_department(self, department_id: str) -> Department | None:
        return self.session.get(Department, department_id)

    def get_department_by_code(self, code: str) -> Department | None:
        return self.session.scalar(select(Department).where(Department.code == code))

    def list_departments(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        include_inactive: bool = False,
    ) -> tuple[list[Department], int]:
        statement = select(Department)
        if not include_inactive:
            statement = statement.where(Department.is_active.is_(True))
        if search:
            statement = statement.where(
                or_(
                    Department.code.icontains(search, autoescape=True),
                    Department.name.icontains(search, autoescape=True),
                )
            )
        total = int(
            self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        items = list(
            self.session.scalars(
                statement.order_by(Department.name).offset((page - 1) * page_size).limit(page_size)
            )
        )
        return items, total

    def get_camera(self, camera_id: str) -> Camera | None:
        return self.session.scalar(
            select(Camera).options(selectinload(Camera.department)).where(Camera.id == camera_id)
        )

    def get_camera_by_code(self, camera_code: str) -> Camera | None:
        return self.session.scalar(
            select(Camera)
            .options(selectinload(Camera.department))
            .where(Camera.camera_code == camera_code)
        )

    def _camera_statement(self, filters: CameraFilters) -> Select[tuple[Camera]]:
        statement = select(Camera).options(selectinload(Camera.department))
        if not filters.include_retired:
            statement = statement.where(Camera.status != "retired")
        if filters.search:
            search = filters.search
            statement = statement.where(
                or_(
                    Camera.camera_code.icontains(search, autoescape=True),
                    Camera.camera_name.icontains(search, autoescape=True),
                    Camera.district.icontains(search, autoescape=True),
                    Camera.city.icontains(search, autoescape=True),
                    Camera.location_description.icontains(search, autoescape=True),
                    Camera.vendor.icontains(search, autoescape=True),
                    Camera.vms.icontains(search, autoescape=True),
                    Camera.department.has(
                        or_(
                            Department.code.icontains(search, autoescape=True),
                            Department.name.icontains(search, autoescape=True),
                        )
                    ),
                )
            )
        exact_filters = (
            (Camera.department_id, filters.department_id),
            (Camera.district, filters.district),
            (Camera.city, filters.city),
            (Camera.vendor, filters.vendor),
            (Camera.vms, filters.vms),
            (Camera.camera_type, filters.camera_type),
            (Camera.status, filters.status),
            (Camera.health, filters.health),
            (Camera.connectivity_type, filters.connectivity_type),
            (Camera.stream_protocol, filters.stream_protocol),
            (Camera.ai_enabled, filters.ai_enabled),
        )
        for column, value in exact_filters:
            if value is not None:
                if column in {
                    Camera.district,
                    Camera.city,
                    Camera.vendor,
                    Camera.vms,
                } and isinstance(value, str):
                    statement = statement.where(func.lower(column) == value.lower())
                else:
                    statement = statement.where(column == value)

        if filters.ai_capability:
            if self.dialect == "postgresql":
                statement = statement.where(text("ai_capabilities ? :ai_capability")).params(
                    ai_capability=filters.ai_capability.lower()
                )
            else:
                statement = statement.where(func.json_array_length(Camera.ai_capabilities) > 0)
        if filters.tag:
            if self.dialect == "postgresql":
                statement = statement.where(text("tags ? :camera_tag")).params(
                    camera_tag=filters.tag.lower()
                )
            else:
                statement = statement.where(func.json_array_length(Camera.tags) > 0)

        if filters.bbox:
            west, south, east, north = filters.bbox
            statement = statement.where(Camera.latitude.between(south, north))
            if west <= east:
                statement = statement.where(Camera.longitude.between(west, east))
            else:
                statement = statement.where(or_(Camera.longitude >= west, Camera.longitude <= east))

        if (
            self.dialect == "postgresql"
            and filters.near_lat is not None
            and filters.near_lon is not None
            and filters.radius_m is not None
        ):
            statement = statement.where(
                text(
                    "ST_DWithin(location_geog, "
                    "ST_SetSRID(ST_MakePoint(:near_lon, :near_lat), 4326)::geography, "
                    ":radius_m)"
                )
            ).params(
                near_lon=filters.near_lon,
                near_lat=filters.near_lat,
                radius_m=filters.radius_m,
            )
        return statement

    def list_cameras(
        self,
        *,
        filters: CameraFilters,
        page: int,
        page_size: int,
    ) -> tuple[list[Camera], int]:
        statement = self._camera_statement(filters)

        requires_python_filter = self.dialect != "postgresql" and (
            filters.ai_capability is not None
            or filters.tag is not None
            or filters.near_lat is not None
        )
        if requires_python_filter:
            candidates = list(self.session.scalars(statement.order_by(Camera.camera_code)))
            if filters.ai_capability:
                capability = filters.ai_capability.lower()
                candidates = [
                    camera for camera in candidates if capability in camera.ai_capabilities
                ]
            if filters.tag:
                tag = filters.tag.lower()
                candidates = [camera for camera in candidates if tag in camera.tags]
            if (
                filters.near_lat is not None
                and filters.near_lon is not None
                and filters.radius_m is not None
            ):
                candidates = [
                    camera
                    for camera in candidates
                    if haversine_m(
                        filters.near_lat,
                        filters.near_lon,
                        camera.latitude,
                        camera.longitude,
                    )
                    <= filters.radius_m
                ]
                candidates.sort(
                    key=lambda camera: haversine_m(
                        filters.near_lat,
                        filters.near_lon,
                        camera.latitude,
                        camera.longitude,
                    )
                )
            total = len(candidates)
            start = (page - 1) * page_size
            return candidates[start : start + page_size], total

        total = int(
            self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        items = list(
            self.session.scalars(
                statement.order_by(Camera.camera_code)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    def camera_filter_options(self, *, include_retired: bool = False) -> dict[str, list[str]]:
        """Return only safe, user-facing values that occur in camera inventory.

        Scalar values are de-duplicated in the database. JSON array expansion is
        intentionally completed in Python so this path has identical behavior on
        PostgreSQL/PostGIS and the SQLite development/test profile.
        """

        def scalar_values(column: Any) -> list[str]:
            statement = select(column).where(column.is_not(None)).distinct()
            if not include_retired:
                statement = statement.where(Camera.status != "retired")
            values = {
                value.strip()
                for value in self.session.scalars(statement)
                if isinstance(value, str) and value.strip()
            }
            return sorted(values, key=lambda value: (value.casefold(), value))

        capability_statement = select(Camera.ai_capabilities)
        if not include_retired:
            capability_statement = capability_statement.where(Camera.status != "retired")
        capabilities = {
            capability.strip()
            for camera_capabilities in self.session.scalars(capability_statement)
            for capability in (camera_capabilities or [])
            if isinstance(capability, str) and capability.strip()
        }

        return {
            "districts": scalar_values(Camera.district),
            "cities": scalar_values(Camera.city),
            "vendors": scalar_values(Camera.vendor),
            "vms": scalar_values(Camera.vms),
            "ai_capabilities": sorted(capabilities, key=lambda value: (value.casefold(), value)),
            "camera_types": scalar_values(Camera.camera_type),
            "connectivity_types": scalar_values(Camera.connectivity_type),
            "stream_protocols": scalar_values(Camera.stream_protocol),
        }

    def camera_statistics(self, *, filters: CameraFilters) -> dict[str, Any]:
        requires_python_filter = self.dialect != "postgresql" and (
            filters.ai_capability is not None
            or filters.tag is not None
            or filters.near_lat is not None
        )
        if requires_python_filter:
            items, _ = self.list_cameras(filters=filters, page=1, page_size=1_000_000)
            by_health: dict[str, int] = {}
            by_status: dict[str, int] = {}
            departments: dict[str, dict[str, Any]] = {}
            for camera in items:
                by_health[camera.health] = by_health.get(camera.health, 0) + 1
                by_status[camera.status] = by_status.get(camera.status, 0) + 1
                department = departments.setdefault(
                    camera.department_id,
                    {
                        "department_id": camera.department_id,
                        "department_code": camera.department.code,
                        "department_name": camera.department.name,
                        "count": 0,
                    },
                )
                department["count"] += 1
            return {
                "total": len(items),
                "ai_enabled": sum(1 for camera in items if camera.ai_enabled),
                "by_health": by_health,
                "by_status": by_status,
                "by_department": sorted(
                    departments.values(), key=lambda item: item["department_name"]
                ),
            }

        filtered = self._camera_statement(filters).subquery()
        total = int(self.session.scalar(select(func.count()).select_from(filtered)) or 0)
        ai_enabled = int(
            self.session.scalar(
                select(func.count()).select_from(filtered).where(filtered.c.ai_enabled.is_(True))
            )
            or 0
        )
        health_rows = self.session.execute(
            select(filtered.c.health, func.count(filtered.c.id)).group_by(filtered.c.health)
        ).all()
        status_rows = self.session.execute(
            select(filtered.c.status, func.count(filtered.c.id)).group_by(filtered.c.status)
        ).all()
        department_rows = self.session.execute(
            select(
                Department.id,
                Department.code,
                Department.name,
                func.count(filtered.c.id),
            )
            .join(filtered, filtered.c.department_id == Department.id)
            .group_by(Department.id, Department.code, Department.name)
            .order_by(Department.name)
        ).all()
        return {
            "total": total,
            "ai_enabled": ai_enabled,
            "by_health": {key: int(count) for key, count in health_rows},
            "by_status": {key: int(count) for key, count in status_rows},
            "by_department": [
                {
                    "department_id": department_id,
                    "department_code": code,
                    "department_name": name,
                    "count": int(count),
                }
                for department_id, code, name, count in department_rows
            ],
        }

    def list_audit_logs(
        self, *, resource_type: str, resource_id: str, page: int, page_size: int
    ) -> tuple[list[AuditLog], int]:
        statement = select(AuditLog).where(
            AuditLog.resource_type == resource_type,
            AuditLog.resource_id == resource_id,
        )
        total = int(
            self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        items = list(
            self.session.scalars(
                statement.order_by(AuditLog.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    def get_import_job(self, idempotency_key: str) -> ImportJob | None:
        return self.session.scalar(
            select(ImportJob).where(ImportJob.idempotency_key == idempotency_key)
        )
