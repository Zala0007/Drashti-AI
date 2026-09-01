from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import AuditLog, CredentialProfile, Department


@dataclass(slots=True)
class CredentialFilters:
    department_id: str | None = None
    enabled: bool | None = None
    search: str | None = None


class CredentialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: object) -> None:
        self.session.add(entity)

    def get(self, profile_id: str) -> CredentialProfile | None:
        return self.session.scalar(
            select(CredentialProfile)
            .options(selectinload(CredentialProfile.department))
            .where(CredentialProfile.id == profile_id)
        )

    def duplicate(
        self, *, department_id: str, name: str, excluding_id: str | None = None
    ) -> CredentialProfile | None:
        statement = select(CredentialProfile).where(
            CredentialProfile.department_id == department_id,
            func.lower(CredentialProfile.name) == name.casefold(),
        )
        if excluding_id:
            statement = statement.where(CredentialProfile.id != excluding_id)
        return self.session.scalar(statement)

    def list(
        self, *, filters: CredentialFilters, page: int, page_size: int
    ) -> tuple[list[CredentialProfile], int]:
        statement = select(CredentialProfile).options(selectinload(CredentialProfile.department))
        if filters.department_id:
            statement = statement.where(CredentialProfile.department_id == filters.department_id)
        if filters.enabled is not None:
            statement = statement.where(CredentialProfile.enabled.is_(filters.enabled))
        if filters.search:
            statement = statement.where(
                or_(
                    CredentialProfile.name.icontains(filters.search, autoescape=True),
                    CredentialProfile.department.has(
                        or_(
                            Department.name.icontains(filters.search, autoescape=True),
                            Department.code.icontains(filters.search, autoescape=True),
                        )
                    ),
                )
            )
        total = int(
            self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        items = list(
            self.session.scalars(
                statement.order_by(CredentialProfile.name)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    def audit(self, *, profile_id: str, page: int, page_size: int) -> tuple[list[AuditLog], int]:
        statement = select(AuditLog).where(
            AuditLog.resource_type == "credential_profile",
            AuditLog.resource_id == profile_id,
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
