export const cameraStatuses = [
  "planned",
  "active",
  "maintenance",
  "inactive",
  "retired",
] as const;

export const healthStatuses = ["unknown", "online", "offline", "degraded"] as const;

export const cameraTypes = [
  "fixed",
  "ptz",
  "dome",
  "bullet",
  "anpr",
  "thermal",
  "panoramic",
  "analog",
  "other",
] as const;

export const connectivityTypes = [
  "fiber",
  "mpls",
  "broadband",
  "cellular_4g",
  "cellular_5g",
  "lan",
  "wireless",
  "satellite",
  "unknown",
] as const;

export const streamProtocols = ["rtsp", "onvif", "hls", "http", "vendor_sdk", "none"] as const;

export const ownershipTypes = ["government", "private", "public_private", "unknown"] as const;

export const aiCapabilityOptions = [
  "anpr",
  "vehicle_detection",
  "vehicle_tracking",
  "person_detection",
  "face_detection",
  "intrusion_detection",
  "crowd_counting",
] as const;

export type CameraStatus = (typeof cameraStatuses)[number];
export type HealthStatus = (typeof healthStatuses)[number];
export type CameraType = (typeof cameraTypes)[number];
export type ConnectivityType = (typeof connectivityTypes)[number];
export type StreamProtocol = (typeof streamProtocols)[number];
export type OwnershipType = (typeof ownershipTypes)[number];
export type AiCapability = (typeof aiCapabilityOptions)[number];

export interface Department {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  is_active?: boolean;
  camera_count?: number;
}

export interface DepartmentCreate {
  code: string;
  name: string;
  description?: string | null;
}

export interface Camera {
  id: string;
  camera_uuid?: string;
  camera_code: string;
  camera_name: string;
  department_id: string;
  department?: Department | null;
  department_name?: string | null;
  district: string;
  city?: string | null;
  location?: string | null;
  location_description?: string | null;
  latitude: number;
  longitude: number;
  camera_type: CameraType;
  vendor?: string | null;
  model?: string | null;
  vms?: string | null;
  connectivity_type: ConnectivityType;
  stream_protocol: StreamProtocol;
  rtsp_capable: boolean;
  onvif_capable: boolean;
  status: CameraStatus;
  health: HealthStatus;
  health_status?: HealthStatus;
  last_heartbeat?: string | null;
  storage_details: Record<string, unknown>;
  ai_enabled?: boolean;
  ai_capabilities: string[];
  installation_date?: string | null;
  owner_name?: string | null;
  ownership: OwnershipType;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface CameraCreate {
  camera_code: string;
  camera_name: string;
  department_id: string;
  district: string;
  city?: string;
  location_description?: string;
  latitude: number;
  longitude: number;
  camera_type: CameraType;
  vendor?: string;
  model?: string;
  vms?: string;
  connectivity_type: ConnectivityType;
  stream_protocol: StreamProtocol;
  rtsp_capable: boolean;
  onvif_capable: boolean;
  status: CameraStatus;
  ai_capabilities: string[];
  storage_details: Record<string, unknown>;
  ownership: OwnershipType;
  owner_name?: string;
  is_public_facing: boolean;
  tags: string[];
}

export interface CameraFilters {
  search: string;
  department_id: string;
  district: string;
  city: string;
  vendor: string;
  vms: string;
  status: "" | CameraStatus;
  health: "" | HealthStatus;
  ai_capability: string;
}

export interface CameraFilterOptions {
  districts: string[];
  cities: string[];
  vendors: string[];
  vms: string[];
  ai_capabilities: string[];
  camera_types: string[];
  connectivity_types: string[];
  stream_protocols: string[];
}

export interface DepartmentCameraCount {
  department_id: string;
  department_code: string;
  department_name: string;
  count: number;
}

export interface CameraStatistics {
  total: number;
  online: number;
  offline: number;
  degraded: number;
  unknown: number;
  ai_enabled: number;
  active?: number;
  planned?: number;
  maintenance?: number;
  inactive?: number;
  retired?: number;
  by_department?: DepartmentCameraCount[];
  by_status?: Record<string, number>;
  by_health?: Record<string, number>;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CameraGeoProperties {
  id?: string;
  camera_uuid?: string;
  camera_code: string;
  camera_name: string;
  department_id?: string;
  department_name?: string | null;
  district?: string;
  city?: string | null;
  status?: CameraStatus;
  health?: HealthStatus;
  health_status?: HealthStatus;
  ai_enabled?: boolean;
  ai_capabilities?: string[];
  location_description?: string | null;
  vendor?: string | null;
  model?: string | null;
  vms?: string | null;
  camera_type?: CameraType;
  connectivity_type?: ConnectivityType;
  stream_protocol?: StreamProtocol;
  last_heartbeat?: string | null;
  [key: string]: unknown;
}

export interface CameraGeoFeature {
  type: "Feature";
  id?: string;
  geometry: {
    type: "Point";
    coordinates: [number, number];
  };
  properties: CameraGeoProperties;
}

export interface CameraGeoJson {
  type: "FeatureCollection";
  features: CameraGeoFeature[];
  number_matched?: number;
  number_returned?: number;
}

export interface AuditEntry {
  id: string;
  action: string;
  actor_name?: string | null;
  actor_id?: string | null;
  source?: string;
  changed_fields?: Record<string, unknown> | null;
  changes?: Record<string, unknown> | null;
  created_at: string;
}

export interface ImportIssue {
  row?: number;
  field?: string;
  message: string;
}

export interface ImportRowResult {
  row_number: number;
  camera_code?: string | null;
  status: "created" | "updated" | "skipped" | "failed";
  camera_id?: string | null;
  error?: { message?: string; [key: string]: unknown } | null;
}

export interface ImportResult {
  import_id?: string;
  idempotency_key?: string;
  replayed?: boolean;
  total_rows?: number;
  created?: number;
  updated?: number;
  skipped?: number;
  failed?: number;
  errors?: ImportIssue[];
  results?: ImportRowResult[];
  message?: string;
}
