export type InvestigationConfidence = "high" | "medium" | "low";

export interface InvestigationCamera {
  id: string;
  camera_code: string;
  camera_name: string;
  district: string;
  city?: string | null;
  location_description?: string | null;
  latitude: number;
  longitude: number;
  bearing_degrees?: number | null;
  health: string;
  status: string;
  ai_enabled: boolean;
  ai_capabilities: string[];
}

export interface InvestigationCase {
  id: string;
  case_number: string;
  target_plate: string;
  target_plate_original: string;
  priority: string;
  reason: string;
  district?: string | null;
  status: string;
  created_by: string;
  started_at: string;
  ended_at?: string | null;
  latest_camera_id?: string | null;
  graph_method: string;
  route_confidence: string;
  last_recalculated_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface InvestigationObservation {
  id: string;
  event: {
    id: string;
    source_event_id: string;
    observed_at: string;
    plate_text: string;
    normalized_plate: string;
    plate_confidence: number;
    direction?: string | null;
    vehicle_attributes: Record<string, unknown>;
    evidence_reference?: string | null;
    model_version?: string | null;
    source: string;
  };
  camera: InvestigationCamera;
  plate_similarity: number;
  temporal_feasibility: number;
  route_feasibility: number;
  correlation_score: number;
  status: "confirmed" | "probable" | "candidate" | "rejected";
  reasoning: string[];
  evidence_class: "observed";
}

export interface InvestigationCandidate {
  id: string;
  camera: InvestigationCamera;
  anchor_camera_id: string;
  rank: number;
  tier: number;
  confidence: InvestigationConfidence;
  eta_min_seconds: number;
  eta_max_seconds: number;
  distance_m: number;
  reasons: string[];
  graph_method: string;
  evidence_class: "predicted";
}

export interface InvestigationRouteSegment {
  source_camera_id: string;
  destination_camera_id: string;
  coordinates: Array<[number, number]>;
  segment_class: "inferred";
  method: string;
  confidence: InvestigationConfidence;
}

export interface InvestigationActivity {
  id: string;
  activity_type: string;
  actor_id: string;
  summary: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface InvestigationWorkspace {
  case: InvestigationCase;
  observations: InvestigationObservation[];
  candidates: InvestigationCandidate[];
  route_segments: InvestigationRouteSegment[];
  activity: InvestigationActivity[];
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  last_confirmed_camera?: InvestigationCamera | null;
  movement_direction?: string | null;
  coverage_gaps: string[];
  prediction_basis: string;
  next_recalculation_seconds: number;
}

export interface InvestigationCreate {
  target_plate: string;
  reason: string;
  priority: "critical" | "high" | "standard";
  district?: string;
}

export interface PredictionBacktest {
  case_id: string;
  eligible_transitions: number;
  evaluated_transitions: number;
  top_1_accuracy?: number | null;
  top_3_accuracy?: number | null;
  top_5_accuracy?: number | null;
  coverage: number;
  evaluation_basis: string;
  steps: Array<{
    anchor_camera: InvestigationCamera;
    actual_next_camera: InvestigationCamera;
    actual_rank?: number | null;
    candidate_count: number;
    graph_method: string;
    hit_at_1: boolean;
    hit_at_3: boolean;
    hit_at_5: boolean;
  }>;
}
