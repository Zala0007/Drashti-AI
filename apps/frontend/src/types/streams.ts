export type ProcessingStreamState =
  | "created"
  | "connecting"
  | "connected"
  | "streaming"
  | "degraded"
  | "reconnecting"
  | "failed"
  | "stopped";

export interface ProcessingStreamMetrics {
  frames_received: number;
  frames_dropped: number;
  frames_sampled_out: number;
  frames_dispatched: number;
  stale_frames_dropped: number;
  dropped_due_to_backpressure: number;
  reconnect_count: number;
  decoder_errors: number;
  queue_depth: number;
  source_fps: number | null;
  decoded_fps: number;
  processing_fps: number;
  current_frame_age_ms: number | null;
  average_frame_age_ms: number | null;
  p95_frame_age_ms: number | null;
  max_frame_age_ms: number | null;
  last_frame_at: string | null;
  last_dispatch_at: string | null;
  clock_offset_ms: number | null;
  resolution: string | null;
  latency_estimate_ms: number | null;
  bitrate_kbps: number | null;
  latest_source_pts_seconds?: number | null;
  pts_timing_active?: boolean;
  source_failover_count?: number;
}

export interface ProcessingStreamCamera {
  id: string;
  camera_code: string;
  camera_name: string;
  department_id: string;
  department_name: string;
  district: string;
  city: string | null;
  latitude: number;
  longitude: number;
  vendor: string | null;
  model: string | null;
  camera_type: string;
  ai_capabilities?: string[];
}

export interface ProcessingStreamSession {
  id: string;
  camera: ProcessingStreamCamera;
  profile: {
    id: string;
    name: string;
    adapter_kind: string;
    stream_role: string;
    endpoint_display: string;
  };
  state: ProcessingStreamState;
  decoder_backend: string;
  transport: string;
  width: number;
  height: number;
  target_fps: number;
  decode_fps: number;
  buffer_capacity: number;
  max_frame_age_ms: number;
  metrics: ProcessingStreamMetrics;
  created_at: string;
  state_changed_at: string;
  connected_at: string | null;
  stopped_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  preview_url: string | null;
}

export interface ProcessingStreamSessionList {
  items: ProcessingStreamSession[];
  total: number;
}

export interface ProcessingStreamStart {
  connection_id?: string;
  preferred_adapter?: "rtsp" | "hls";
  target_fps?: number;
  decode_fps?: number;
  transport?: "tcp" | "udp";
  max_frame_age_ms?: number;
}

export interface StreamAggregateMetrics {
  active_streams: number;
  offline_streams: number;
  degraded_streams: number;
  reconnecting_streams: number;
  average_decoded_fps: number;
  average_processing_fps: number;
  average_latency_ms: number;
  total_frames_received: number;
  total_frames_dropped: number;
  total_reconnects: number;
  scheduler_queue_depth: number;
  ai_consumer_attached: boolean;
  worker_cpu_percent: number;
  worker_memory_mb: number;
  worker_processes: number;
  gpu_decode_utilization_percent: number | null;
  network_receive_mbps: number | null;
  states: Record<ProcessingStreamState, number>;
}

export interface StreamCapabilities {
  available: boolean;
  decoder_backend: string | null;
  decoder_source: string | null;
  configured_backend: string;
  hardware_decode_active: boolean;
  hardware_decode_reason?: string;
  gpu_zero_copy_active: boolean;
  latest_frame_semantics: boolean;
  batch_dispatch: boolean;
  max_active_sessions: number;
  supported_source_types: string[];
}

export interface AnalyticsDetection {
  kind: "object" | "plate";
  class_id: number;
  class_name: string;
  confidence: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  plate_text: string | null;
  ocr_confidence: number | null;
  track_id: number | null;
}

export interface CameraAnalytics {
  camera_id: string;
  stream_id: string;
  frame_number: number;
  observed_at: string;
  status: string;
  model: string;
  device: string;
  inference_ms: number;
  detections: AnalyticsDetection[];
  routed_modules: string[];
  error_message: string | null;
}

export interface CameraAnalyticsList {
  items: CameraAnalytics[];
  total: number;
}

export interface AnalyticsCapabilities {
  enabled: boolean;
  status: "disabled" | "initializing" | "active" | "unavailable" | string;
  consumer_attached: boolean;
  model: string | null;
  device: string | null;
  reason: string | null;
  routes: string[];
}
