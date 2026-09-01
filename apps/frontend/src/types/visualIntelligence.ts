export type VisualMatchLevel = "HIGH" | "MEDIUM" | "LOW";
export type VisualAnalysisStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "RETRY_PENDING" | "SKIPPED";

export interface VisualDamageRegion {
  location: string;
  description: string;
  confidence: "low" | "medium" | "high";
}

export interface VisualIntelligenceRecord {
  id: number;
  event_id: string;
  detection_id: number;
  vehicle_crop_uri: string;
  plate_crop_uri?: string | null;
  plate_id?: number | null;
  camera_id: string;
  track_id?: number | null;
  timestamp_ms: number;
  observed_at: string;
  anpr_plate?: string | null;
  vehicle_present: boolean;
  vehicle_type: string;
  vehicle_type_confidence: string;
  primary_color: string;
  secondary_colors: string[];
  damage_status: string;
  damage_regions: VisualDamageRegion[];
  visual_condition: string;
  distinctive_features: string[];
  accessories: string[];
  vehicle_view: string;
  plate_visibility: string;
  lighting_condition: string;
  image_quality: string;
  occlusion: string;
  short_description: string;
  detailed_description: string;
  search_keywords: string[];
  analysis_confidence: string;
  vlm_provider: string;
  vlm_model: string;
  vlm_prompt_version: string;
  analyzed_at?: string | null;
  analysis_status: VisualAnalysisStatus;
  analysis_error?: string | null;
}

export interface VisualSearchResult extends VisualIntelligenceRecord {
  match_level: VisualMatchLevel;
  match_reasons: string[];
}

export interface VisualSearchFilters {
  vehicle_type?: string;
  primary_color?: string;
  damage_status?: string;
  damage_location?: string;
  plate_visibility?: string;
  image_quality?: string;
  camera_ids?: string[];
  date_from?: string;
  date_to?: string;
  time_from?: string;
  time_to?: string;
}

export interface VisualSearchResponse {
  query: string;
  total_results: number;
  page: number;
  page_size: number;
  pages: number;
  summary: string;
  parsed_filters: Record<string, unknown>;
  results: VisualSearchResult[];
}

export interface VisualIntelligenceStatus {
  provider: string;
  model: string;
  prompt_version: string;
  configured: boolean;
  worker_running: boolean;
  queue_depth: number;
  total_vehicle_crops: number;
  completed: number;
  pending: number;
  processing: number;
  failed: number;
  skipped: number;
  average_processing_ms?: number | null;
  last_successful_request?: string | null;
}

export interface VisualQueueResponse {
  queued: number;
  skipped: number;
  queue_depth: number;
  message: string;
}
