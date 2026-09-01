from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_plate(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", value.upper())
    if not 6 <= len(normalized) <= 14:
        raise ValueError("registration must contain 6-14 letters or numbers")
    return normalized


class InvestigationStatus(StrEnum):
    created = "created"
    searching_history = "searching_history"
    target_located = "target_located"
    active_tracking = "active_tracking"
    target_temporarily_lost = "target_temporarily_lost"
    reacquired = "reacquired"
    suspended = "suspended"
    completed = "completed"
    cancelled = "cancelled"


class InvestigationSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    @model_validator(mode="after")
    def normalize_datetimes(self) -> InvestigationSchema:
        for name in type(self).model_fields:
            value = getattr(self, name, None)
            if isinstance(value, datetime):
                object.__setattr__(
                    self,
                    name,
                    value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC),
                )
        return self


class InvestigationCreate(InvestigationSchema):
    target_plate: str = Field(min_length=6, max_length=32)
    reason: str = Field(min_length=10, max_length=1000)
    priority: Literal["critical", "high", "standard"] = "high"
    district: str | None = Field(default=None, max_length=100)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @field_validator("target_plate")
    @classmethod
    def validate_plate(cls, value: str) -> str:
        normalize_plate(value)
        return value.upper()

    @model_validator(mode="after")
    def validate_window(self) -> InvestigationCreate:
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValueError("end_time must be after start_time")
        return self


class ANPREventCreate(InvestigationSchema):
    source_event_id: str = Field(min_length=1, max_length=160)
    camera_id: UUID
    observed_at: datetime
    plate_text: str = Field(min_length=1, max_length=32)
    plate_confidence: float = Field(ge=0, le=1)
    direction: str | None = Field(default=None, max_length=32)
    vehicle_attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_reference: str | None = Field(default=None, max_length=500)
    model_version: str | None = Field(default=None, max_length=120)
    source: str = Field(default="anpr_pipeline", min_length=2, max_length=60)

    @field_validator("plate_text")
    @classmethod
    def validate_plate(cls, value: str) -> str:
        normalize_plate(value)
        return value.upper()


class InvestigationTransition(InvestigationSchema):
    status: Literal["suspended", "completed", "cancelled", "active_tracking"]
    reason: str = Field(min_length=5, max_length=500)


class CameraSummary(InvestigationSchema):
    id: UUID
    camera_code: str
    camera_name: str
    district: str
    city: str | None
    location_description: str | None
    latitude: float
    longitude: float
    bearing_degrees: float | None
    health: str
    status: str
    ai_enabled: bool
    ai_capabilities: list[str]


class ANPREventRead(InvestigationSchema):
    id: UUID
    source_event_id: str
    camera_id: UUID
    observed_at: datetime
    received_at: datetime
    plate_text: str
    normalized_plate: str
    plate_confidence: float
    direction: str | None
    vehicle_attributes: dict[str, Any]
    evidence_reference: str | None
    model_version: str | None
    source: str


class ObservationRead(InvestigationSchema):
    id: UUID
    event: ANPREventRead
    camera: CameraSummary
    plate_similarity: float
    temporal_feasibility: float
    route_feasibility: float
    correlation_score: float
    status: Literal["confirmed", "probable", "candidate", "rejected"]
    reasoning: list[str]
    evidence_class: Literal["observed"] = "observed"


class CandidateRead(InvestigationSchema):
    id: UUID
    camera: CameraSummary
    anchor_camera_id: UUID
    rank: int
    tier: int
    confidence: Literal["high", "medium", "low"]
    eta_min_seconds: int
    eta_max_seconds: int
    distance_m: float
    reasons: list[str]
    graph_method: str
    evidence_class: Literal["predicted"] = "predicted"


class RouteSegmentRead(InvestigationSchema):
    source_camera_id: UUID
    destination_camera_id: UUID
    coordinates: list[tuple[float, float]]
    segment_class: Literal["inferred"] = "inferred"
    method: str
    confidence: Literal["high", "medium", "low"]


class ActivityRead(InvestigationSchema):
    id: UUID
    activity_type: str
    actor_id: str
    summary: str
    details: dict[str, Any]
    created_at: datetime


class InvestigationCaseRead(InvestigationSchema):
    id: UUID
    case_number: str
    target_plate: str
    target_plate_original: str
    priority: str
    reason: str
    district: str | None
    status: str
    created_by: str
    started_at: datetime
    ended_at: datetime | None
    latest_camera_id: UUID | None
    graph_method: str
    route_confidence: str
    last_recalculated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvestigationWorkspace(InvestigationSchema):
    case: InvestigationCaseRead
    observations: list[ObservationRead]
    candidates: list[CandidateRead]
    route_segments: list[RouteSegmentRead]
    activity: list[ActivityRead]
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    last_confirmed_camera: CameraSummary | None
    movement_direction: str | None
    coverage_gaps: list[str]
    prediction_basis: str
    next_recalculation_seconds: int


class InvestigationList(InvestigationSchema):
    items: list[InvestigationCaseRead]
    total: int


class PredictionBacktestStep(InvestigationSchema):
    anchor_camera: CameraSummary
    actual_next_camera: CameraSummary
    actual_rank: int | None
    candidate_count: int
    graph_method: str
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool


class PredictionBacktestRead(InvestigationSchema):
    case_id: UUID
    eligible_transitions: int
    evaluated_transitions: int
    top_1_accuracy: float | None
    top_3_accuracy: float | None
    top_5_accuracy: float | None
    coverage: float
    evaluation_basis: str
    steps: list[PredictionBacktestStep]


class DemoScenarioRequest(InvestigationSchema):
    target_plate: str = "GJ01AB1234"

    @field_validator("target_plate")
    @classmethod
    def validate_plate(cls, value: str) -> str:
        return normalize_plate(value)


class DemoScenarioRead(InvestigationSchema):
    target_plate: str
    events_created: int
    cameras_used: int
    disclosure: str
