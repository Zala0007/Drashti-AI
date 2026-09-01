import type { AuditEntry, Page } from "./registry";

export interface FederationAdapter {
  kind: string;
  label: string;
  version: string;
  description?: string;
  schemes: string[];
  capabilities: string[];
  probe_supported: boolean;
  discovery_supported: boolean;
  stream_handoff_supported: boolean;
  availability: string | boolean;
  availability_message?: string | null;
  supports_probe?: boolean;
  supports_discovery?: boolean;
  supports_stream_handoff?: boolean;
  available?: boolean;
  unavailable_reason?: string | null;
}

export interface FederationAdapterCatalog {
  items: FederationAdapter[];
}

export interface FederationConnection {
  id: string;
  camera_id: string;
  camera_code: string;
  camera_name: string;
  department_name?: string | null;
  district?: string | null;
  city?: string | null;
  name: string;
  adapter_kind: string;
  adapter_label?: string | null;
  stream_role: string;
  endpoint_display?: string | null;
  has_credential_reference: boolean;
  enabled: boolean;
  priority: number;
  verification_status: string;
  last_probe_at?: string | null;
  last_probe_latency_ms?: number | null;
  last_error_code?: string | null;
  last_error_message?: string | null;
  last_success_at?: string | null;
  failure_count: number;
  normalized_metadata?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  endpoint_fingerprint?: string | null;
  encryption_key_id?: string | null;
  created_by?: string | null;
  camera?: {
    id: string;
    camera_code: string;
    camera_name: string;
    department_id?: string | null;
    department_code?: string | null;
    department_name?: string | null;
    district?: string | null;
    city?: string | null;
    latitude?: number | null;
    longitude?: number | null;
  };
}

export interface FederationStatistics {
  total: number;
  enabled: number;
  reachable: number;
  attention: number;
  unverified: number;
  by_status: Record<string, number>;
  by_adapter: Record<string, number>;
  disabled?: number;
  healthy_ratio?: number;
  last_probe_at?: string | null;
}

export interface GovernmentFeed {
  external_id: string;
  number: number;
  name: string;
  location: string;
  live: boolean;
  codec?: string | null;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  bitrate_kbps?: number | null;
  camera_id?: string | null;
  camera_code?: string | null;
  primary_connection_id?: string | null;
  fallback_connection_id?: string | null;
  sync_state: "new" | "onboarded" | "incomplete";
}

export interface GovernmentFeedCatalogue {
  configured: boolean;
  provider: string;
  fetched_at?: string | null;
  total: number;
  live: number;
  h264: number;
  h265: number;
  metadata_pending: number;
  items: GovernmentFeed[];
}

export interface GovernmentFeedSyncResult {
  provider: string;
  fetched_at: string;
  discovered: number;
  live: number;
  cameras_created: number;
  cameras_updated: number;
  cameras_unchanged: number;
  connections_created: number;
  connections_updated: number;
  connections_unchanged: number;
  provisional_geospatial_records: number;
  items: GovernmentFeed[];
}

export interface FederationConnectionFilters {
  search: string;
  camera_id: string;
  adapter_kind: string;
  verification_status: string;
  enabled: "" | "true" | "false";
}

export interface FederationConnectionCreate {
  camera_id: string;
  name: string;
  adapter_kind: string;
  endpoint: string;
  stream_role: string;
  credential_reference?: string;
  priority: number;
  enabled: boolean;
}

export interface FederationConnectionPatch {
  name?: string;
  stream_role?: string;
  credential_reference?: string | null;
  priority?: number;
}

export interface CredentialProfile {
  id: string;
  reference: string;
  department: {
    id: string;
    code: string;
    name: string;
  };
  name: string;
  auth_type: "username_password";
  enabled: boolean;
  has_username: boolean;
  has_secret: boolean;
  encryption_key_id: string;
  created_by: string;
  last_used_at?: string | null;
  created_at: string;
  updated_at: string;
}

export type CredentialProfilePage = Page<CredentialProfile>;

export interface CredentialProfileCreate {
  department_id: string;
  name: string;
  username: string;
  password: string;
  enabled: boolean;
}

export interface CredentialProfilePatch {
  name?: string;
  username?: string;
  password?: string;
  enabled?: boolean;
}

export interface FederationAuditEntry extends AuditEntry {
  connection_id?: string;
}

export type FederationConnectionPage = Page<FederationConnection>;

export type RuntimeSessionState =
  | "starting"
  | "live"
  | "degraded"
  | "backoff"
  | "stopped"
  | "failed"
  | "unavailable"
  | string;

export interface RuntimeCapabilities {
  available: boolean;
  binary_source: string;
  supported_adapter_kinds: string[];
  unsupported_adapter_kinds: string[];
  output_protocol: string;
  segment_duration_seconds: number;
  playlist_window: number;
  decoder_backend?: string;
  hardware_decode_active?: boolean;
  hardware_decode_reason?: string;
  video_processing_mode?: string;
  credential_resolver_mode: string;
  supervision: {
    watchdog_seconds: number;
    max_backoff_seconds: number;
  };
  boundary: string;
}

export interface RuntimeSession {
  id: string;
  connection_id: string;
  state: RuntimeSessionState;
  decoder_backend?: string;
  camera: {
    id: string;
    camera_code: string;
    camera_name: string;
    department_name?: string | null;
    district?: string | null;
    city?: string | null;
  };
  profile: {
    id: string;
    name: string;
    adapter_kind: string;
    stream_role: string;
    endpoint_display?: string | null;
  };
  playlist_url?: string | null;
  metrics: {
    frame?: number | null;
    fps?: number | null;
    out_time_ms?: number | null;
    progress_at?: string | null;
  };
  restart_count: number;
  started_at?: string | null;
  state_changed_at: string;
  last_progress_at?: string | null;
  last_playlist_at?: string | null;
  stopped_at?: string | null;
  last_error_code?: string | null;
  last_error_message?: string | null;
}

export interface RuntimeSessionList {
  items: RuntimeSession[];
  total: number;
}
