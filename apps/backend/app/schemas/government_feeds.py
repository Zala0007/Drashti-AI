from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.registry import RegistrySchema


class GovernmentFeedRead(RegistrySchema):
    external_id: str
    number: int
    name: str
    location: str
    live: bool
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    bitrate_kbps: int | None
    camera_id: UUID | None = None
    camera_code: str | None = None
    primary_connection_id: UUID | None = None
    fallback_connection_id: UUID | None = None
    sync_state: Literal["new", "onboarded", "incomplete"]


class GovernmentFeedCatalogueRead(RegistrySchema):
    configured: bool
    provider: str
    fetched_at: datetime | None
    total: int
    live: int
    h264: int
    h265: int
    metadata_pending: int
    items: list[GovernmentFeedRead]


class GovernmentFeedSyncRequest(RegistrySchema):
    include_offline: bool = True
    create_hls_fallback: bool = True


class GovernmentFeedSyncRead(RegistrySchema):
    provider: str
    fetched_at: datetime
    discovered: int
    live: int
    cameras_created: int
    cameras_updated: int
    cameras_unchanged: int
    connections_created: int
    connections_updated: int
    connections_unchanged: int
    provisional_geospatial_records: int
    items: list[GovernmentFeedRead] = Field(max_length=500)
