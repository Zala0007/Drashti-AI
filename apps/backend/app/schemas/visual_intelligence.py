from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ConfidenceLevel = Literal["low", "medium", "high"]
AnalysisStatus = Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED", "RETRY_PENDING", "SKIPPED"]


class DamageRegion(BaseModel):
    location: str = Field(max_length=80)
    description: str = Field(max_length=400)
    confidence: ConfidenceLevel = "low"


class VehicleVisualProfile(BaseModel):
    vehicle_present: bool = True
    vehicle_type: str = Field(default="unknown", max_length=60)
    vehicle_type_confidence: ConfidenceLevel = "low"
    primary_color: str = Field(default="unknown", max_length=60)
    secondary_colors: list[str] = Field(default_factory=list, max_length=5)
    visual_condition: str = Field(default="uncertain", max_length=300)
    damage_present: Literal["none_obvious", "possible", "visible", "uncertain"] = "uncertain"
    damage_regions: list[DamageRegion] = Field(default_factory=list, max_length=8)
    distinctive_features: list[str] = Field(default_factory=list, max_length=16)
    accessories: list[str] = Field(default_factory=list, max_length=12)
    vehicle_view: str = Field(default="unknown", max_length=60)
    plate_visibility: Literal["readable", "partial", "unreadable", "not_visible", "uncertain"] = (
        "uncertain"
    )
    lighting_condition: str = Field(default="unknown", max_length=80)
    image_quality: Literal["poor", "fair", "good", "unknown"] = "unknown"
    occlusion: Literal["none", "low", "medium", "high", "unknown"] = "unknown"
    search_keywords: list[str] = Field(default_factory=list, max_length=30)
    short_description: str = Field(max_length=500)
    detailed_description: str = Field(max_length=2000)
    analysis_confidence: ConfidenceLevel = "low"

    @field_validator(
        "secondary_colors",
        "distinctive_features",
        "accessories",
        "search_keywords",
        mode="before",
    )
    @classmethod
    def clean_list(cls, values: object) -> list[str]:
        if isinstance(values, str):
            values = values.split(",")
        if not isinstance(values, list):
            return []
        result: list[str] = []
        for raw in values:
            value = str(raw).strip().lower()
            if value and value not in result:
                result.append(value[:160])
        return result


class VisualIntelligenceRead(BaseModel):
    id: int
    event_id: str
    detection_id: int
    vehicle_crop_uri: str
    plate_crop_uri: str | None = None
    plate_id: int | None = None
    camera_id: str
    track_id: int | None = None
    timestamp_ms: float
    observed_at: str
    anpr_plate: str | None = None
    vehicle_present: bool = True
    vehicle_type: str
    vehicle_type_confidence: str = "low"
    primary_color: str
    secondary_colors: list[str] = Field(default_factory=list)
    damage_status: str
    damage_regions: list[DamageRegion] = Field(default_factory=list)
    visual_condition: str
    distinctive_features: list[str] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    vehicle_view: str
    plate_visibility: str
    lighting_condition: str = "unknown"
    image_quality: str
    occlusion: str = "unknown"
    short_description: str
    detailed_description: str
    search_keywords: list[str] = Field(default_factory=list)
    analysis_confidence: str
    vlm_provider: str
    vlm_model: str
    vlm_prompt_version: str
    analyzed_at: str | None = None
    analysis_status: AnalysisStatus
    analysis_error: str | None = None


class VisualSearchFilters(BaseModel):
    vehicle_type: str | None = Field(default=None, max_length=60)
    primary_color: str | None = Field(default=None, max_length=60)
    damage_status: str | None = Field(default=None, max_length=40)
    damage_location: str | None = Field(default=None, max_length=80)
    plate_visibility: str | None = Field(default=None, max_length=40)
    image_quality: str | None = Field(default=None, max_length=20)
    camera_ids: list[str] = Field(default_factory=list, max_length=50)
    date_from: str | None = None
    date_to: str | None = None
    time_from: str | None = None
    time_to: str | None = None


class VisualSearchRequest(BaseModel):
    query: str = Field(default="", max_length=300)
    filters: VisualSearchFilters = Field(default_factory=VisualSearchFilters)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=18, ge=1, le=48)


class VisualSearchResult(VisualIntelligenceRead):
    match_level: Literal["HIGH", "MEDIUM", "LOW"]
    match_reasons: list[str] = Field(default_factory=list)


class VisualSearchResponse(BaseModel):
    query: str
    total_results: int
    page: int
    page_size: int
    pages: int
    summary: str
    parsed_filters: dict[str, object] = Field(default_factory=dict)
    results: list[VisualSearchResult] = Field(default_factory=list)


class VisualBackfillRequest(BaseModel):
    limit: int = Field(default=24, ge=1, le=200)
    retry_failed: bool = False


class VisualQueueResponse(BaseModel):
    queued: int
    skipped: int
    queue_depth: int
    message: str


class VisualIntelligenceStatus(BaseModel):
    provider: str
    model: str
    prompt_version: str
    configured: bool
    worker_running: bool
    queue_depth: int
    total_vehicle_crops: int
    completed: int
    pending: int
    processing: int
    failed: int
    skipped: int
    average_processing_ms: float | None = None
    last_successful_request: str | None = None
