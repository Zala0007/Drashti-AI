export interface AIClassCount {
  class_name: string;
  count: number;
  average_confidence: number;
}

export interface AIModelStatus {
  model_id: string;
  key: string;
  name: string;
  purpose: string;
  status: string;
  detail: string;
  output_count: number;
}

export interface AIFeatureStatus {
  key: string;
  name: string;
  status: string;
  description: string;
  evidence: string;
}

export interface AIShowcaseOverview {
  available: boolean;
  total_detections: number;
  vehicle_detections: number;
  plate_detections: number;
  readable_plate_detections: number;
  consensus_plate_detections: number;
  visual_profiles: number;
  visual_pending: number;
  visual_failed: number;
  unique_tracks: number;
  source_count: number;
  frame_count: number;
  average_confidence: number;
  average_ocr_confidence: number;
  first_observed_at: string | null;
  last_observed_at: string | null;
  class_counts: AIClassCount[];
  models: AIModelStatus[];
  features: AIFeatureStatus[];
  disclosure: string;
}

export interface AIDetection {
  id: number;
  evidence_id: string;
  model_id: string;
  model_name: string;
  source_label: string;
  frame: number;
  time_ms: number;
  track_id: number | null;
  class_id: number;
  class_name: string;
  confidence: number;
  box: number[];
  width: number;
  height: number;
  created_at: string;
  image_url: string;
}

export interface AIOCRCandidate {
  provider: string;
  status: string;
  raw_text: string | null;
  normalized_text: string | null;
  confidence: number | null;
  processing_ms: number | null;
  error: string | null;
}

export interface AIPlateDetection {
  id: number;
  evidence_id: string;
  detector_model_id: string;
  detector_model_name: string;
  ocr_model_id: string;
  source_detection_id: number | null;
  source_label: string;
  frame: number;
  time_ms: number;
  track_id: number | null;
  plate_text: string | null;
  ocr_confidence: number | null;
  ocr_raw_text: string | null;
  ocr_raw_confidence: number | null;
  ocr_consensus_count: number;
  ocr_candidates: AIOCRCandidate[];
  ocr_selected_provider: string | null;
  ocr_decision: string | null;
  ocr_decision_reason: string | null;
  ocr_review_required: boolean;
  detection_confidence: number;
  box: number[];
  width: number;
  height: number;
  ocr_provider: string;
  ocr_status: string;
  source_vehicle_evidence_id: string | null;
  source_vehicle_image_url: string | null;
  created_at: string;
  image_url: string;
}

export interface AIPage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}
