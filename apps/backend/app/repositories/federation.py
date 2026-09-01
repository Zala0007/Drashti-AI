from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import AuditLog, Camera, ConnectionProfile


@dataclass(slots=True)
class ConnectionFilters:
    camera_id: str | None = None
    adapter_kind: str | None = None
    verification_status: str | None = None
    enabled: bool | None = None
    search: str | None = None


class FederationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: Any) -> None:
        self.session.add(entity)

    def get_camera(self, camera_id: str) -> Camera | None:
        return self.session.get(Camera, camera_id)

    def get_connection(self, connection_id: str) -> ConnectionProfile | None:
        return self.session.scalar(
            select(ConnectionProfile)
            .options(selectinload(ConnectionProfile.camera).selectinload(Camera.department))
            .where(ConnectionProfile.id == connection_id)
        )

    def get_duplicate(
        self,
        *,
        camera_id: str,
        name: str,
        stream_role: str,
        excluding_id: str | None = None,
    ) -> ConnectionProfile | None:
        statement = select(ConnectionProfile).where(
            ConnectionProfile.camera_id == camera_id,
            func.lower(ConnectionProfile.name) == name.lower(),
            ConnectionProfile.stream_role == stream_role,
        )
        if excluding_id:
            statement = statement.where(ConnectionProfile.id != excluding_id)
        return self.session.scalar(statement)

    def _statement(self, filters: ConnectionFilters) -> Select[tuple[ConnectionProfile]]:
        statement = select(ConnectionProfile).options(
            selectinload(ConnectionProfile.camera).selectinload(Camera.department)
        )
        if filters.camera_id:
            statement = statement.where(ConnectionProfile.camera_id == filters.camera_id)
        if filters.adapter_kind:
            statement = statement.where(ConnectionProfile.adapter_kind == filters.adapter_kind)
        if filters.verification_status:
            statement = statement.where(
                ConnectionProfile.verification_status == filters.verification_status
            )
        if filters.enabled is not None:
            statement = statement.where(ConnectionProfile.enabled.is_(filters.enabled))
        if filters.search:
            search = filters.search
            statement = statement.where(
                or_(
                    ConnectionProfile.name.icontains(search, autoescape=True),
                    ConnectionProfile.endpoint_display.icontains(search, autoescape=True),
                    ConnectionProfile.endpoint_fingerprint.icontains(search, autoescape=True),
                    ConnectionProfile.camera.has(
                        or_(
                            Camera.camera_code.icontains(search, autoescape=True),
                            Camera.camera_name.icontains(search, autoescape=True),
                            Camera.district.icontains(search, autoescape=True),
                        )
                    ),
                )
            )
        return statement

    def list_connections(
        self, *, filters: ConnectionFilters, page: int, page_size: int
    ) -> tuple[list[ConnectionProfile], int]:
        statement = self._statement(filters)
        total = int(
            self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        items = list(
            self.session.scalars(
                statement.order_by(
                    ConnectionProfile.enabled.desc(),
                    ConnectionProfile.priority,
                    ConnectionProfile.name,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    def statistics(self, *, filters: ConnectionFilters) -> dict[str, Any]:
        filtered = self._statement(filters).subquery()
        total = int(self.session.scalar(select(func.count()).select_from(filtered)) or 0)
        enabled = int(
            self.session.scalar(
                select(func.count()).select_from(filtered).where(filtered.c.enabled.is_(True))
            )
            or 0
        )
        status_rows = self.session.execute(
            select(filtered.c.verification_status, func.count(filtered.c.id)).group_by(
                filtered.c.verification_status
            )
        ).all()
        adapter_rows = self.session.execute(
            select(filtered.c.adapter_kind, func.count(filtered.c.id)).group_by(
                filtered.c.adapter_kind
            )
        ).all()
        last_probe_at = self.session.scalar(select(func.max(filtered.c.last_probe_at)))
        return {
            "total": total,
            "enabled": enabled,
            "disabled": total - enabled,
            "by_status": {key: int(count) for key, count in status_rows},
            "by_adapter_kind": {key: int(count) for key, count in adapter_rows},
            "healthy_ratio": round(
                100
                * next(
                    (int(count) for key, count in status_rows if key == "reachable"),
                    0,
                )
                / total,
                2,
            )
            if total
            else 0.0,
            "last_probe_at": last_probe_at,
        }

    def list_audit_logs(
        self, *, connection_id: str, page: int, page_size: int
    ) -> tuple[list[AuditLog], int]:
        statement = select(AuditLog).where(
            AuditLog.resource_type == "connection_profile",
            AuditLog.resource_id == connection_id,
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
