from __future__ import annotations

from pydantic import BaseModel, Field


class AIClassCount(BaseModel):
    class_name: str
    count: int
    average_confidence: float


class AIModelStatus(BaseModel):
    model_id: str
    key: str
    name: str
    purpose: str
    status: str
    detail: str
    output_count: int = 0


class AIFeatureStatus(BaseModel):
    key: str
    name: str
    status: str
    description: str
    evidence: str


class AIShowcaseOverview(BaseModel):
    available: bool
    total_detections: int = 0
    vehicle_detections: int = 0
    plate_detections: int = 0
    readable_plate_detections: int = 0
    consensus_plate_detections: int = 0
    visual_profiles: int = 0
    visual_pending: int = 0
    visual_failed: int = 0
    unique_tracks: int = 0
    source_count: int = 0
    frame_count: int = 0
    average_confidence: float = 0.0
    average_ocr_confidence: float = 0.0
    first_observed_at: str | None = None
    last_observed_at: str | None = None
    class_counts: list[AIClassCount] = Field(default_factory=list)
    models: list[AIModelStatus] = Field(default_factory=list)
    features: list[AIFeatureStatus] = Field(default_factory=list)
    disclosure: str


class AIDetectionRead(BaseModel):
    id: int
    evidence_id: str
    model_id: str
    model_name: str
    source_label: str
    frame: int
    time_ms: float
    track_id: int | None
    class_id: int
    class_name: str
    confidence: float
    box: list[float]
    width: int
    height: int
    created_at: str
    image_url: str


class AIDetectionPage(BaseModel):
    items: list[AIDetectionRead]
    total: int
    page: int
    page_size: int
    pages: int


class OCRCandidateRead(BaseModel):
    provider: str
    status: str
    raw_text: str | None = None
    normalized_text: str | None = None
    confidence: float | None = None
    processing_ms: float | None = None
    error: str | None = None


class AIPlateRead(BaseModel):
    id: int
    evidence_id: str
    detector_model_id: str
    detector_model_name: str
    ocr_model_id: str
    source_detection_id: int | None
    source_label: str
    frame: int
    time_ms: float
    track_id: int | None
    plate_text: str | None
    ocr_confidence: float | None
    ocr_raw_text: str | None = None
    ocr_raw_confidence: float | None = None
    ocr_consensus_count: int = 0
    ocr_candidates: list[OCRCandidateRead] = Field(default_factory=list)
    ocr_selected_provider: str | None = None
    ocr_decision: str | None = None
    ocr_decision_reason: str | None = None
    ocr_review_required: bool = False
    detection_confidence: float
    box: list[float]
    width: int
    height: int
    ocr_provider: str
    ocr_status: str
    source_vehicle_evidence_id: str | None = None
    source_vehicle_image_url: str | None = None
    created_at: str
    image_url: str


class AIPlatePage(BaseModel):
    items: list[AIPlateRead]
    total: int
    page: int
    page_size: int
    pages: int
