import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveOperationsPage } from "./LiveOperationsPage";

const jsonResponse = (body: unknown): Response => new Response(JSON.stringify(body), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

const camera = {
  id: "camera-1",
  camera_code: "HOME-AHD-001",
  camera_name: "Ashram Road ANPR",
  department_id: "department-1",
  department: { id: "department-1", code: "HOME", name: "Home Department" },
  department_name: "Home Department",
  district: "Ahmedabad",
  city: "Ahmedabad",
  latitude: 23.03,
  longitude: 72.58,
  camera_type: "anpr",
  vendor: "Hikvision",
  model: "DS-Test",
  vms: "District VMS",
  connectivity_type: "fiber",
  stream_protocol: "rtsp",
  rtsp_capable: true,
  onvif_capable: true,
  status: "active",
  health: "online",
  storage_details: {},
  ai_capabilities: ["anpr", "vehicle_detection"],
  ownership: "government",
  tags: [],
  created_at: "2026-08-27T09:00:00Z",
  updated_at: "2026-08-27T09:00:00Z",
};

const session = {
  id: "stream-1",
  camera: {
    id: "camera-1",
    camera_code: "HOME-AHD-001",
    camera_name: "Ashram Road ANPR",
    department_id: "department-1",
    department_name: "Home Department",
    district: "Ahmedabad",
    city: "Ahmedabad",
    latitude: 23.03,
    longitude: 72.58,
    vendor: "Hikvision",
    model: "DS-Test",
    camera_type: "anpr",
  },
  profile: {
    id: "profile-1",
    name: "Detection substream",
    adapter_kind: "rtsp",
    stream_role: "substream",
    endpoint_display: "rtsp://c***a/…",
  },
  state: "streaming",
  decoder_backend: "ffmpeg",
  transport: "tcp",
  width: 640,
  height: 360,
  target_fps: 10,
  decode_fps: 12,
  buffer_capacity: 2,
  max_frame_age_ms: 750,
  metrics: {
    frames_received: 150,
    frames_dropped: 4,
    frames_sampled_out: 2,
    frames_dispatched: 80,
    stale_frames_dropped: 0,
    dropped_due_to_backpressure: 4,
    reconnect_count: 1,
    decoder_errors: 1,
    queue_depth: 2,
    source_fps: 25,
    decoded_fps: 11.8,
    processing_fps: 9.9,
    current_frame_age_ms: 42,
    average_frame_age_ms: 38,
    p95_frame_age_ms: 60,
    max_frame_age_ms: 71,
    last_frame_at: "2026-08-27T09:00:00Z",
    last_dispatch_at: "2026-08-27T09:00:00Z",
    clock_offset_ms: null,
    resolution: "640x360",
    latency_estimate_ms: 42,
    bitrate_kbps: null,
  },
  created_at: "2026-08-27T09:00:00Z",
  state_changed_at: "2026-08-27T09:00:01Z",
  connected_at: "2026-08-27T09:00:01Z",
  stopped_at: null,
  last_error_code: null,
  last_error_message: null,
  preview_url: "/api/v1/streams/camera-1/preview.jpg",
};

describe("P04 live operations page", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows real stream telemetry, camera details and an honest AI handoff state", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/streams/metrics")) return Promise.resolve(jsonResponse({
        active_streams: 1,
        offline_streams: 0,
        degraded_streams: 0,
        reconnecting_streams: 0,
        average_decoded_fps: 11.8,
        average_processing_fps: 9.9,
        average_latency_ms: 42,
        total_frames_received: 150,
        total_frames_dropped: 4,
        total_reconnects: 1,
        scheduler_queue_depth: 1,
        ai_consumer_attached: false,
        worker_cpu_percent: 18.2,
        worker_memory_mb: 220,
        worker_processes: 2,
        gpu_decode_utilization_percent: null,
        network_receive_mbps: null,
        states: { created: 0, connecting: 0, connected: 0, streaming: 1, degraded: 0, reconnecting: 0, failed: 0, stopped: 0 },
      }));
      if (url.includes("/streams/capabilities")) return Promise.resolve(jsonResponse({
        available: true,
        decoder_backend: "ffmpeg",
        decoder_source: "configured",
        configured_backend: "auto",
        hardware_decode_active: false,
        gpu_zero_copy_active: false,
        latest_frame_semantics: true,
        batch_dispatch: true,
        max_active_sessions: 28,
        supported_source_types: ["rtsp"],
      }));
      if (url.endsWith("/streams")) return Promise.resolve(jsonResponse({ items: [session], total: 1 }));
      if (url.includes("/cameras")) return Promise.resolve(jsonResponse({ items: [camera], total: 1, page: 1, page_size: 100, pages: 1 }));
      return Promise.resolve(jsonResponse({}));
    }));

    render(<LiveOperationsPage />);

    expect(await screen.findByRole("heading", { name: "Live Operations Matrix" })).toBeInTheDocument();
    expect(await screen.findByText("Ashram Road ANPR")).toBeInTheDocument();
    expect(screen.getByText("FFmpeg ready")).toBeInTheDocument();
    expect(screen.getByText("P05 consumer interface ready")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Continuous live feed from Ashram Road ANPR" }))
      .toHaveAttribute("src", expect.stringContaining("/preview.jpg"));

    const tile = screen.getByText("Ashram Road ANPR").closest("article");
    expect(tile).not.toBeNull();
    fireEvent.click(tile!);
    const inspector = screen.getByText("Camera intelligence").closest("aside");
    expect(inspector).not.toBeNull();
    expect(within(inspector!).getByText("P04 frame bus ready")).toBeInTheDocument();
    expect(within(inspector!).getByText("Hikvision · DS-Test")).toBeInTheDocument();
    expect(within(inspector!).getByText("11.8 fps")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Search live cameras" }), {
      target: { value: "Surat" },
    });
    expect(screen.getByText("No camera matches the current wall search.")).toBeInTheDocument();
  });

  it("submits the entire camera grid without sequential preview blocking", async () => {
    const cameras = Array.from({ length: 30 }, (_, index) => ({
      ...camera,
      id: `camera-${index + 1}`,
      camera_code: `GOV-LIVE-${index + 1}`,
      camera_name: `Government camera ${index + 1}`,
    }));
    const startRequests: string[] = [];
    let activeStarts = 0;
    let maximumConcurrentStarts = 0;

    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/streams/metrics")) return Promise.resolve(jsonResponse({
        active_streams: 0,
        offline_streams: 0,
        degraded_streams: 0,
        reconnecting_streams: 0,
        average_decoded_fps: 0,
        average_processing_fps: 0,
        average_latency_ms: 0,
        total_frames_received: 0,
        total_frames_dropped: 0,
        total_reconnects: 0,
        scheduler_queue_depth: 0,
        ai_consumer_attached: false,
        worker_cpu_percent: 0,
        worker_memory_mb: 0,
        worker_processes: 0,
        gpu_decode_utilization_percent: null,
        network_receive_mbps: null,
        states: { created: 0, connecting: 0, connected: 0, streaming: 0, degraded: 0, reconnecting: 0, failed: 0, stopped: 0 },
      }));
      if (url.includes("/streams/capabilities")) return Promise.resolve(jsonResponse({
        available: true,
        decoder_backend: "ffmpeg",
        decoder_source: "configured",
        configured_backend: "auto",
        hardware_decode_active: false,
        gpu_zero_copy_active: false,
        latest_frame_semantics: true,
        batch_dispatch: true,
        max_active_sessions: 32,
        supported_source_types: ["hls", "rtsp"],
      }));
      if (url.endsWith("/streams")) return Promise.resolve(jsonResponse({ items: [], total: 0 }));
      if (url.includes("/cameras")) return Promise.resolve(jsonResponse({ items: cameras, total: 30, page: 1, page_size: 100, pages: 1 }));
      if (url.endsWith("/start")) {
        startRequests.push(url);
        activeStarts += 1;
        maximumConcurrentStarts = Math.max(maximumConcurrentStarts, activeStarts);
        const cameraId = url.split("/").at(-2) ?? "camera-1";
        const selected = cameras.find((item) => item.id === cameraId) ?? cameras[0];
        return new Promise<Response>((resolve) => {
          window.setTimeout(() => {
            activeStarts -= 1;
            resolve(jsonResponse({
              ...session,
              id: `stream-${cameraId}`,
              state: "connecting",
              camera: {
                ...session.camera,
                id: selected.id,
                camera_code: selected.camera_code,
                camera_name: selected.camera_name,
              },
            }));
          }, 8);
        });
      }
      return Promise.resolve(jsonResponse({}));
    }));

    render(<LiveOperationsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Start grid (30)" }));

    // Normal wall interaction stays available while the controlled start queue runs.
    fireEvent.change(screen.getByRole("textbox", { name: "Search live cameras" }), {
      target: { value: "GOV-LIVE-30" },
    });
    expect(screen.getByText("Government camera 30")).toBeInTheDocument();

    await waitFor(() => expect(startRequests).toHaveLength(30));
    expect(maximumConcurrentStarts).toBeLessThanOrEqual(3);
  });
});
