from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import BadRequestError, ConflictError, NotFoundError
from app.federation import EndpointCipher
from app.models import AuditLog, CredentialProfile, Department
from app.repositories import CredentialFilters, CredentialRepository
from app.schemas.credentials import (
    CredentialDepartmentRead,
    CredentialProfileCreate,
    CredentialProfileList,
    CredentialProfileRead,
    CredentialProfileUpdate,
)
from app.schemas.federation import ConnectionAuditList
from app.schemas.registry import AuditRead, page_count


def _secret_text(value: str, *, field: str) -> str:
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise BadRequestError(
            "CREDENTIAL_VALUE_INVALID",
            f"{field} must be non-empty and cannot contain control characters",
        )
    return value


class CredentialProfileService:
    def __init__(
        self,
        session: Session,
        *,
        cipher: EndpointCipher,
        actor_id: str,
        request_id: str | None,
    ) -> None:
        self.session = session
        self.repository = CredentialRepository(session)
        self.cipher = cipher
        self.actor_id = actor_id
        self.request_id = request_id

    @staticmethod
    def _read(profile: CredentialProfile) -> CredentialProfileRead:
        return CredentialProfileRead(
            id=profile.id,
            reference=f"credential-profile:{profile.id}",
            department=CredentialDepartmentRead(
                id=profile.department.id,
                code=profile.department.code,
                name=profile.department.name,
            ),
            name=profile.name,
            auth_type=profile.auth_type,
            enabled=profile.enabled,
            has_username=bool(profile.username_ciphertext),
            has_secret=bool(profile.secret_ciphertext),
            encryption_key_id=profile.encryption_key_id,
            created_by=profile.created_by,
            last_used_at=profile.last_used_at,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    def _audit(self, profile: CredentialProfile, action: str, changes: dict[str, Any]) -> None:
        self.repository.add(
            AuditLog(
                resource_type="credential_profile",
                resource_id=profile.id,
                action=action,
                actor_id=self.actor_id,
                request_id=self.request_id,
                source="api",
                changes=changes,
            )
        )

    def _commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(
                "CREDENTIAL_PROFILE_EXISTS",
                "A credential profile with this name already exists for the department",
            ) from exc

    def create(self, payload: CredentialProfileCreate) -> CredentialProfileRead:
        department = self.session.get(Department, str(payload.department_id))
        if not department:
            raise NotFoundError("department", str(payload.department_id))
        name = payload.name.strip()
        if self.repository.duplicate(department_id=department.id, name=name):
            raise ConflictError(
                "CREDENTIAL_PROFILE_EXISTS",
                "A credential profile with this name already exists for the department",
            )
        username = _secret_text(payload.username.get_secret_value(), field="username")
        password = _secret_text(payload.password.get_secret_value(), field="password")
        profile = CredentialProfile(
            department_id=department.id,
            name=name,
            auth_type="username_password",
            username_ciphertext=self.cipher.encrypt(username),
            secret_ciphertext=self.cipher.encrypt(password),
            encryption_key_id=self.cipher.key_id,
            enabled=payload.enabled,
            created_by=self.actor_id,
        )
        profile.department = department
        self.repository.add(profile)
        self.session.flush()
        self._audit(
            profile,
            "credential.created",
            {
                "department_id": department.id,
                "enabled": profile.enabled,
                "auth_type": profile.auth_type,
            },
        )
        self._commit()
        self.session.refresh(profile)
        return self._read(profile)

    def get(self, profile_id: str) -> CredentialProfileRead:
        profile = self.repository.get(profile_id)
        if not profile:
            raise NotFoundError("credential_profile", profile_id)
        return self._read(profile)

    def list(
        self, *, filters: CredentialFilters, page: int, page_size: int
    ) -> CredentialProfileList:
        items, total = self.repository.list(filters=filters, page=page, page_size=page_size)
        return CredentialProfileList(
            items=[self._read(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            pages=page_count(total, page_size),
        )

    def update(self, profile_id: str, payload: CredentialProfileUpdate) -> CredentialProfileRead:
        profile = self.repository.get(profile_id)
        if not profile:
            raise NotFoundError("credential_profile", profile_id)
        changes: dict[str, Any] = {}
        if "name" in payload.model_fields_set and payload.name is not None:
            name = payload.name.strip()
            if self.repository.duplicate(
                department_id=profile.department_id, name=name, excluding_id=profile.id
            ):
                raise ConflictError(
                    "CREDENTIAL_PROFILE_EXISTS",
                    "A credential profile with this name already exists for the department",
                )
            changes["name_changed"] = profile.name != name
            profile.name = name
        if "username" in payload.model_fields_set and payload.username is not None:
            username = _secret_text(payload.username.get_secret_value(), field="username")
            profile.username_ciphertext = self.cipher.encrypt(username)
            changes["username_rotated"] = True
        if "password" in payload.model_fields_set and payload.password is not None:
            password = _secret_text(payload.password.get_secret_value(), field="password")
            profile.secret_ciphertext = self.cipher.encrypt(password)
            changes["secret_rotated"] = True
        if {"username", "password"} & payload.model_fields_set:
            profile.encryption_key_id = self.cipher.key_id
        if "enabled" in payload.model_fields_set and payload.enabled is not None:
            changes["enabled"] = {"from": profile.enabled, "to": payload.enabled}
            profile.enabled = payload.enabled
        self._audit(profile, "credential.updated", changes)
        self._commit()
        self.session.refresh(profile)
        return self._read(profile)

    def audit(self, profile_id: str, *, page: int, page_size: int) -> ConnectionAuditList:
        if not self.repository.get(profile_id):
            raise NotFoundError("credential_profile", profile_id)
        items, total = self.repository.audit(profile_id=profile_id, page=page, page_size=page_size)
        return ConnectionAuditList(
            items=[AuditRead.model_validate(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            pages=page_count(total, page_size),
        )
