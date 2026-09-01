from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.investigation import normalize_plate
from app.schemas.registry import RegistrySchema


class WatchlistEntryCreate(RegistrySchema):
    plate_text: str = Field(min_length=5, max_length=32)
    subject_label: str = Field(min_length=3, max_length=160)
    reason: str = Field(min_length=5, max_length=2000)
    severity: Literal["critical", "high", "standard"] = "high"
    valid_until: datetime | None = None

    @field_validator("plate_text")
    @classmethod
    def valid_plate(cls, value: str) -> str:
        normalized = normalize_plate(value)
        if len(normalized) < 5:
            raise ValueError("plate_text must contain a usable registration")
        return value


class WatchlistEntryUpdate(RegistrySchema):
    status: Literal["active", "inactive"]
    reason: str | None = Field(default=None, min_length=5, max_length=2000)
    valid_until: datetime | None = None


class WatchlistEntryRead(RegistrySchema):
    id: UUID
    plate_text: str
    normalized_plate: str
    subject_label: str
    reason: str
    severity: str
    status: str
    valid_from: datetime
    valid_until: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class WatchlistEntryList(RegistrySchema):
    items: list[WatchlistEntryRead]
    total: int


class WatchlistAlertAction(RegistrySchema):
    status: Literal["acknowledged", "resolved", "false_positive"] = "acknowledged"


class WatchlistAlertRead(RegistrySchema):
    id: UUID
    status: str
    match_score: float
    matched_plate: str
    observed_at: datetime
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    created_at: datetime
    entry: WatchlistEntryRead
    anpr_event_id: UUID
    camera_id: UUID
    camera_code: str
    camera_name: str
    district: str
    evidence_reference: str | None
    ocr_confidence: float


class WatchlistAlertList(RegistrySchema):
    items: list[WatchlistAlertRead]
    total: int
    unacknowledged: int


class WatchlistDashboard(RegistrySchema):
    active_entries: int
    total_entries: int
    new_alerts: int
    latest_alert_at: datetime | None


class WatchlistSeedRequest(RegistrySchema):
    plates: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_plates(self) -> WatchlistSeedRequest:
        normalized = [normalize_plate(value) for value in self.plates]
        if len(set(normalized)) != len(normalized):
            raise ValueError("plates must be unique")
        return self
