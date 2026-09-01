from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.registry import RegistrySchema


class AdvancedCameraRead(RegistrySchema):
    id: UUID
    camera_code: str
    camera_name: str
    district: str
    city: str | None
    latitude: float
    longitude: float
    health: str
    status: str
    vendor: str | None
    vms: str | None
    coverage_radius_m: float | None
    bearing_degrees: float | None
    field_of_view_degrees: float | None


class VehicleObservationCreate(RegistrySchema):
    source_observation_id: str = Field(min_length=3, max_length=160)
    camera_id: UUID
    anpr_event_id: UUID | None = None
    observed_at: datetime
    track_id: str | None = Field(default=None, max_length=120)
    plate_text: str | None = Field(default=None, max_length=32)
    vehicle_class: str | None = Field(default=None, max_length=60)
    colour: str | None = Field(default=None, max_length=60)
    direction: str | None = Field(default=None, max_length=32)
    bounding_box: list[float] = Field(default_factory=list, max_length=4)
    image_width: int | None = Field(default=None, ge=1, le=32768)
    image_height: int | None = Field(default=None, ge=1, le=32768)
    quality_score: float = Field(ge=0, le=1)
    quality_flags: list[str] = Field(default_factory=list, max_length=12)
    crop_reference: str | None = Field(default=None, max_length=500)
    embedding: list[float] | None = Field(default=None, min_length=2, max_length=2048)
    embedding_provider: str | None = Field(default=None, max_length=120)
    model_version: str | None = Field(default=None, max_length=180)
    source: str = Field(default="vehicle_analytics", max_length=80)

    @field_validator("bounding_box")
    @classmethod
    def validate_box(cls, value: list[float]) -> list[float]:
        if value and (len(value) != 4 or value[2] <= value[0] or value[3] <= value[1]):
            raise ValueError("bounding_box must be [x1, y1, x2, y2] with positive area")
        return value

    @model_validator(mode="after")
    def validate_embedding(self) -> VehicleObservationCreate:
        if self.embedding is not None and not self.embedding_provider:
            raise ValueError("embedding_provider is required with an embedding")
        return self


class VehicleObservationRead(RegistrySchema):
    id: UUID
    source_observation_id: str
    camera: AdvancedCameraRead
    anpr_event_id: UUID | None
    observed_at: datetime
    track_id: str | None
    plate_text: str | None
    normalized_plate: str | None
    vehicle_class: str | None
    colour: str | None
    direction: str | None
    bounding_box: list[float]
    image_width: int | None
    image_height: int | None
    quality_score: float
    quality_flags: list[str]
    crop_available: bool
    embedding_available: bool
    embedding_provider: str | None
    model_version: str | None
    source: str
    created_at: datetime


class ReIDQuery(RegistrySchema):
    target_observation_id: UUID | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    max_candidates: int = Field(default=20, ge=1, le=50)


class ReIDReview(RegistrySchema):
    status: Literal["confirmed", "rejected", "candidate"]
    note: str = Field(min_length=5, max_length=1000)


class ReIDMatchRead(RegistrySchema):
    id: UUID
    investigation_id: UUID
    target: VehicleObservationRead
    candidate: VehicleObservationRead
    visual_similarity: float | None
    plate_similarity: float | None
    colour_similarity: float | None
    class_similarity: float | None
    temporal_feasibility: float
    route_feasibility: float
    direction_consistency: float | None
    technical_score: float
    assessment: Literal["high", "medium", "low"]
    status: Literal["confirmed", "probable", "candidate", "rejected"]
    reasons: list[str]
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime


class ReIDResult(RegistrySchema):
    investigation_id: UUID
    target_observation_id: UUID | None
    items: list[ReIDMatchRead]
    compared_observations: int
    elapsed_ms: float
    disclosure: str


class DemoReIDRead(RegistrySchema):
    observations_created: int
    disclosure: str


class CaseCreate(RegistrySchema):
    title: str = Field(min_length=5, max_length=240)
    description: str = Field(min_length=10, max_length=5000)
    case_type: str = Field(default="vehicle_investigation", min_length=3, max_length=60)
    priority: Literal["critical", "high", "standard"] = "high"
    assigned_to: str | None = Field(default=None, max_length=160)
    district: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=160)
    authorization_reference: str = Field(min_length=5, max_length=200)
    retention_class: str = Field(default="investigation_standard", min_length=3, max_length=60)
    investigation_id: UUID | None = None


class CaseTransition(RegistrySchema):
    status: Literal["open", "active", "on_hold", "closed", "archived"]
    reason: str = Field(min_length=5, max_length=1000)


class EvidenceAttach(RegistrySchema):
    source_type: Literal[
        "anpr_event", "investigation_observation", "reid_match", "route_summary", "alert"
    ]
    source_id: str = Field(min_length=3, max_length=160)
    evidence_type: str = Field(min_length=3, max_length=60)
    classification: Literal["restricted", "confidential", "internal"] = "restricted"
    notes: str | None = Field(default=None, max_length=3000)


class CaseActivityCreate(RegistrySchema):
    action: Literal["note.added", "evidence.tagged", "case.reviewed"]
    summary: str = Field(min_length=3, max_length=500)
    details: dict[str, Any] = Field(default_factory=dict)


class CaseRead(RegistrySchema):
    id: UUID
    case_number: str
    title: str
    description: str
    case_type: str
    priority: str
    status: str
    created_by: str
    assigned_to: str | None
    district: str | None
    department: str | None
    authorization_reference: str
    retention_class: str
    investigation_id: UUID | None
    created_at: datetime
    updated_at: datetime


class EvidenceRead(RegistrySchema):
    id: UUID
    case_id: UUID
    source_type: str
    source_id: str
    camera: AdvancedCameraRead | None
    occurred_at: datetime
    evidence_type: str
    sha256: str | None
    created_by: str
    model_version: str | None
    confidence: float | None
    classification: str
    notes: str | None
    metadata: dict[str, Any]
    retrieval_available: bool
    created_at: datetime


class CaseActivityRead(RegistrySchema):
    id: UUID
    case_id: UUID
    evidence_id: UUID | None
    action: str
    actor_id: str
    summary: str
    details: dict[str, Any]
    created_at: datetime


class CaseWorkspace(RegistrySchema):
    case: CaseRead
    target_plate: str | None
    evidence: list[EvidenceRead]
    activity: list[CaseActivityRead]
    route_camera_sequence: list[AdvancedCameraRead]
    integrity_verified: int
    integrity_unavailable: int


class CaseList(RegistrySchema):
    items: list[CaseRead]
    total: int


class CaseExportRead(RegistrySchema):
    generated_at: datetime
    generated_by: str
    format: Literal["structured_case_summary"] = "structured_case_summary"
    integrity_disclosure: str
    workspace: CaseWorkspace


HealthState = Literal["healthy", "degraded", "critical", "offline", "unknown", "maintenance"]


class HealthAggregateCreate(RegistrySchema):
    source_sample_id: str | None = Field(default=None, max_length=160)
    camera_id: UUID
    bucket_start: datetime
    bucket_seconds: int = Field(default=300, ge=60, le=3600)
    availability: float = Field(ge=0, le=1)
    decoded_fps: float | None = Field(default=None, ge=0, le=240)
    processing_fps: float | None = Field(default=None, ge=0, le=240)
    latency_ms: float | None = Field(default=None, ge=0, le=300_000)
    frame_age_ms: float | None = Field(default=None, ge=0, le=3_600_000)
    reconnect_count: int = Field(default=0, ge=0)
    decoder_errors: int = Field(default=0, ge=0)
    freeze_events: int = Field(default=0, ge=0)
    authentication_failures: int = Field(default=0, ge=0)
    image_quality_state: Literal["good", "degraded", "possible_obstruction", "not_measured"] = (
        "not_measured"
    )
    edge_node_id: str | None = Field(default=None, max_length=120)
    ai_worker_state: Literal["healthy", "degraded", "offline", "unknown"] = "unknown"
    source: str = Field(default="edge_aggregate", max_length=60)
    details: dict[str, Any] = Field(default_factory=dict)


class HealthAggregateRead(RegistrySchema):
    id: UUID
    camera: AdvancedCameraRead
    bucket_start: datetime
    bucket_seconds: int
    health_state: HealthState
    availability: float
    decoded_fps: float | None
    processing_fps: float | None
    latency_ms: float | None
    frame_age_ms: float | None
    reconnect_count: int
    decoder_errors: int
    freeze_events: int
    authentication_failures: int
    image_quality_state: str
    edge_node_id: str | None
    ai_worker_state: str
    source: str
    details: dict[str, Any]
    created_at: datetime


class MaintenanceRead(RegistrySchema):
    id: UUID
    camera: AdvancedCameraRead
    finding_key: str
    risk: Literal["high", "medium", "low"]
    priority: Literal["critical", "high", "standard"]
    status: str
    indicators: list[str]
    explanation: str
    first_detected_at: datetime
    last_detected_at: datetime
    created_at: datetime
    updated_at: datetime


class HealthIncidentRead(RegistrySchema):
    id: UUID
    incident_type: str
    severity: str
    status: str
    title: str
    explanation: str
    edge_node_id: str | None
    affected_camera_ids: list[UUID]
    first_detected_at: datetime
    last_detected_at: datetime


class HealthDashboard(RegistrySchema):
    total_cameras: int
    states: dict[str, int]
    maintenance_risk: dict[str, int]
    latest: list[HealthAggregateRead]
    findings: list[MaintenanceRead]
    incidents: list[HealthIncidentRead]
    telemetry_basis: str


class HealthHistoryRead(RegistrySchema):
    camera: AdvancedCameraRead
    items: list[HealthAggregateRead]
    telemetry_basis: str


class CoverageRunRequest(RegistrySchema):
    district: str | None = Field(default=None, max_length=100)
    gap_threshold_m: float = Field(default=25_000, ge=500, le=100_000)
    redundancy_radius_m: float = Field(default=5_000, ge=100, le=50_000)


class CoverageGapRead(RegistrySchema):
    id: UUID
    gap_type: Literal["permanent", "temporary"]
    severity: Literal["critical", "high", "medium", "low"]
    latitude: float
    longitude: float
    radius_m: float
    source_camera_id: UUID | None
    destination_camera_id: UUID | None
    explanation: str
    confidence_basis: str


class DeploymentCandidateRead(RegistrySchema):
    id: UUID
    latitude: float
    longitude: float
    priority: str
    area_label: str
    reasons: list[str]
    estimated_radius_m: float
    assumption: str


class CriticalCoverageNode(RegistrySchema):
    camera: AdvancedCameraRead
    nearest_backup_distance_m: float | None
    reason: str


class CoverageAnalysisRead(RegistrySchema):
    id: UUID
    district: str | None
    analysis_type: str
    assumptions: list[str]
    camera_count: int
    operational_count: int
    duration_ms: float
    created_by: str
    created_at: datetime
    gaps: list[CoverageGapRead]
    deployment_candidates: list[DeploymentCandidateRead]
    critical_nodes: list[CriticalCoverageNode]
    metrics: dict[str, int]


class CoverageWhatIfRequest(RegistrySchema):
    camera_id: UUID


class CoverageWhatIfRead(RegistrySchema):
    simulation: Literal[True] = True
    camera: AdvancedCameraRead
    nearest_backup: AdvancedCameraRead | None
    nearest_backup_distance_m: float | None
    estimated_coverage_lost_radius_m: float
    critical_gap_created: bool
    affected_investigation_ids: list[UUID]
    assumptions: list[str]
