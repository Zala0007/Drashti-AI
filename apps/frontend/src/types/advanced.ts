export interface IntelligenceCamera {
  id: string;
  camera_code: string;
  camera_name: string;
  district: string;
  city?: string | null;
  latitude: number;
  longitude: number;
  health: string;
  status: string;
  vendor?: string | null;
  vms?: string | null;
  coverage_radius_m?: number | null;
  bearing_degrees?: number | null;
  field_of_view_degrees?: number | null;
}

export interface VehicleObservation {
  id: string;
  source_observation_id: string;
  camera: IntelligenceCamera;
  anpr_event_id?: string | null;
  observed_at: string;
  track_id?: string | null;
  plate_text?: string | null;
  normalized_plate?: string | null;
  vehicle_class?: string | null;
  colour?: string | null;
  direction?: string | null;
  quality_score: number;
  quality_flags: string[];
  crop_available: boolean;
  embedding_available: boolean;
  embedding_provider?: string | null;
  model_version?: string | null;
  source: string;
}

export interface ReIDMatch {
  id: string;
  investigation_id: string;
  target: VehicleObservation;
  candidate: VehicleObservation;
  visual_similarity?: number | null;
  plate_similarity?: number | null;
  colour_similarity?: number | null;
  class_similarity?: number | null;
  temporal_feasibility: number;
  route_feasibility: number;
  direction_consistency?: number | null;
  technical_score: number;
  assessment: "high" | "medium" | "low";
  status: "confirmed" | "probable" | "candidate" | "rejected";
  reasons: string[];
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  review_note?: string | null;
}

export interface ReIDResult {
  investigation_id: string;
  target_observation_id?: string | null;
  items: ReIDMatch[];
  compared_observations: number;
  elapsed_ms: number;
  disclosure: string;
}

export interface CaseFile {
  id: string;
  case_number: string;
  title: string;
  description: string;
  case_type: string;
  priority: string;
  status: string;
  created_by: string;
  assigned_to?: string | null;
  district?: string | null;
  department?: string | null;
  authorization_reference: string;
  retention_class: string;
  investigation_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseEvidence {
  id: string;
  case_id: string;
  source_type: string;
  source_id: string;
  camera?: IntelligenceCamera | null;
  occurred_at: string;
  evidence_type: string;
  sha256?: string | null;
  created_by: string;
  model_version?: string | null;
  confidence?: number | null;
  classification: string;
  notes?: string | null;
  metadata: Record<string, unknown>;
  retrieval_available: boolean;
  created_at: string;
}

export interface CaseActivity {
  id: string;
  action: string;
  actor_id: string;
  summary: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface CaseWorkspace {
  case: CaseFile;
  target_plate?: string | null;
  evidence: CaseEvidence[];
  activity: CaseActivity[];
  route_camera_sequence: IntelligenceCamera[];
  integrity_verified: number;
  integrity_unavailable: number;
}

export interface HealthAggregate {
  id: string;
  camera: IntelligenceCamera;
  bucket_start: string;
  bucket_seconds: number;
  health_state: string;
  availability: number;
  decoded_fps?: number | null;
  processing_fps?: number | null;
  latency_ms?: number | null;
  frame_age_ms?: number | null;
  reconnect_count: number;
  decoder_errors: number;
  freeze_events: number;
  authentication_failures: number;
  image_quality_state: string;
  edge_node_id?: string | null;
  ai_worker_state: string;
  source: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface MaintenanceFinding {
  id: string;
  camera: IntelligenceCamera;
  risk: "high" | "medium" | "low";
  priority: string;
  status: string;
  indicators: string[];
  explanation: string;
  last_detected_at: string;
}

export interface HealthIncident {
  id: string;
  incident_type: string;
  severity: string;
  status: string;
  title: string;
  explanation: string;
  edge_node_id?: string | null;
  affected_camera_ids: string[];
  first_detected_at: string;
  last_detected_at: string;
}

export interface HealthDashboard {
  total_cameras: number;
  states: Record<string, number>;
  maintenance_risk: Record<string, number>;
  latest: HealthAggregate[];
  findings: MaintenanceFinding[];
  incidents: HealthIncident[];
  telemetry_basis: string;
}

export interface HealthHistory {
  camera: IntelligenceCamera;
  items: HealthAggregate[];
  telemetry_basis: string;
}

export interface CoverageGap {
  id: string;
  gap_type: "permanent" | "temporary";
  severity: string;
  latitude: number;
  longitude: number;
  radius_m: number;
  source_camera_id?: string | null;
  destination_camera_id?: string | null;
  explanation: string;
  confidence_basis: string;
}

export interface DeploymentCandidate {
  id: string;
  latitude: number;
  longitude: number;
  priority: string;
  area_label: string;
  reasons: string[];
  estimated_radius_m: number;
  assumption: string;
}

export interface CriticalCoverageNode {
  camera: IntelligenceCamera;
  nearest_backup_distance_m?: number | null;
  reason: string;
}

export interface CoverageAnalysis {
  id: string;
  district?: string | null;
  analysis_type: string;
  assumptions: string[];
  camera_count: number;
  operational_count: number;
  duration_ms: number;
  created_by: string;
  created_at: string;
  gaps: CoverageGap[];
  deployment_candidates: DeploymentCandidate[];
  critical_nodes: CriticalCoverageNode[];
  metrics: Record<string, number>;
}

export interface CoverageWhatIf {
  simulation: true;
  camera: IntelligenceCamera;
  nearest_backup?: IntelligenceCamera | null;
  nearest_backup_distance_m?: number | null;
  estimated_coverage_lost_radius_m: number;
  critical_gap_created: boolean;
  affected_investigation_ids: string[];
  assumptions: string[];
}
