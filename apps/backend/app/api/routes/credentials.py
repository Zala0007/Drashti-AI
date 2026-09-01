from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_credential_filters, get_credential_profile_service
from app.repositories import CredentialFilters
from app.schemas.credentials import (
    CredentialProfileCreate,
    CredentialProfileList,
    CredentialProfileRead,
    CredentialProfileUpdate,
)
from app.schemas.federation import ConnectionAuditList
from app.services import CredentialProfileService

router = APIRouter(prefix="/federation/credentials", tags=["federation-credentials"])


@router.get("", response_model=CredentialProfileList)
def list_credential_profiles(
    service: Annotated[CredentialProfileService, Depends(get_credential_profile_service)],
    filters: Annotated[CredentialFilters, Depends(get_credential_filters)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CredentialProfileList:
    return service.list(filters=filters, page=page, page_size=page_size)


@router.post("", response_model=CredentialProfileRead, status_code=status.HTTP_201_CREATED)
def create_credential_profile(
    payload: CredentialProfileCreate,
    service: Annotated[CredentialProfileService, Depends(get_credential_profile_service)],
) -> CredentialProfileRead:
    return service.create(payload)


@router.get("/{profile_id}", response_model=CredentialProfileRead)
def get_credential_profile(
    profile_id: UUID,
    service: Annotated[CredentialProfileService, Depends(get_credential_profile_service)],
) -> CredentialProfileRead:
    return service.get(str(profile_id))


@router.patch("/{profile_id}", response_model=CredentialProfileRead)
def update_credential_profile(
    profile_id: UUID,
    payload: CredentialProfileUpdate,
    service: Annotated[CredentialProfileService, Depends(get_credential_profile_service)],
) -> CredentialProfileRead:
    return service.update(str(profile_id), payload)


@router.get("/{profile_id}/audit", response_model=ConnectionAuditList)
def credential_profile_audit(
    profile_id: UUID,
    service: Annotated[CredentialProfileService, Depends(get_credential_profile_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ConnectionAuditList:
    return service.audit(str(profile_id), page=page, page_size=page_size)
