from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, model_validator

from app.schemas.registry import RegistrySchema


class CredentialProfileCreate(RegistrySchema):
    department_id: UUID
    name: str = Field(min_length=2, max_length=160)
    username: SecretStr = Field(min_length=1, max_length=256)
    password: SecretStr = Field(min_length=1, max_length=1024)
    enabled: bool = True


class CredentialProfileUpdate(RegistrySchema):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    username: SecretStr | None = Field(default=None, min_length=1, max_length=256)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=1024)
    enabled: bool | None = None

    @model_validator(mode="after")
    def ensure_change(self) -> CredentialProfileUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        for field_name in {"name", "username", "password", "enabled"} & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class CredentialDepartmentRead(RegistrySchema):
    id: UUID
    code: str
    name: str


class CredentialProfileRead(RegistrySchema):
    id: UUID
    reference: str
    department: CredentialDepartmentRead
    name: str
    auth_type: Literal["username_password"]
    enabled: bool
    has_username: bool
    has_secret: bool
    encryption_key_id: str
    created_by: str
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CredentialProfileList(RegistrySchema):
    items: list[CredentialProfileRead]
    total: int
    page: int
    page_size: int
    pages: int
