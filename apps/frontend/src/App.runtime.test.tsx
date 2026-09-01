import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const jsonResponse = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status,
  headers: { "Content-Type": "application/json" },
});

const emptyPage = { items: [], total: 0, page: 1, page_size: 100, pages: 0 };
const emptyStats = {
  total: 0,
  online: 0,
  offline: 0,
  degraded: 0,
  unknown: 0,
  ai_enabled: 0,
  by_department: [],
  by_status: {},
  by_health: {},
};
const emptyGeoJson = { type: "FeatureCollection", features: [], number_matched: 0, number_returned: 0 };
const emptyOptions = { districts: [], cities: [], vendors: [], vms: [], ai_capabilities: [], camera_types: [], connectivity_types: [], stream_protocols: [] };
const emptyStreamMetrics = {
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
  worker_processes: 1,
  gpu_decode_utilization_percent: null,
  network_receive_mbps: null,
  states: {
    created: 0,
    connecting: 0,
    connected: 0,
    streaming: 0,
    degraded: 0,
    reconnecting: 0,
    failed: 0,
    stopped: 0,
  },
};
const streamCapabilities = {
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
};

function apiFetch(input: RequestInfo | URL): Promise<Response> {
  const url = String(input);
  if (url.includes("/streams/metrics")) {
    return Promise.resolve(jsonResponse(emptyStreamMetrics));
  }
  if (url.includes("/streams/capabilities")) {
    return Promise.resolve(jsonResponse(streamCapabilities));
  }
  if (url.endsWith("/streams")) return Promise.resolve(jsonResponse({ items: [], total: 0 }));
  if (url.includes("/federation/adapters")) return Promise.resolve(jsonResponse({ items: [] }));
  if (url.includes("/federation/connections/statistics")) return Promise.resolve(jsonResponse({ total: 0, enabled: 0, disabled: 0, by_status: {}, by_adapter_kind: {}, healthy_ratio: 0, last_probe_at: null }));
  if (url.includes("/federation/connections")) return Promise.resolve(jsonResponse(emptyPage));
  if (url.includes("/departments")) return Promise.resolve(jsonResponse(emptyPage));
  if (url.includes("/cameras/filter-options")) return Promise.resolve(jsonResponse(emptyOptions));
  if (url.includes("/cameras/statistics")) return Promise.resolve(jsonResponse(emptyStats));
  if (url.includes("/cameras/geojson")) return Promise.resolve(jsonResponse(emptyGeoJson));
  if (url.includes("/cameras")) return Promise.resolve(jsonResponse(emptyPage));
  return Promise.resolve(jsonResponse({}));
}

describe("Drishti application runtime", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "#/command");
  });

  it("opens on the live command centre and navigates every implemented page", async () => {
    const fetchMock = vi.fn(apiFetch);
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(screen.getByRole("heading", { name: "Unified CCTV Intelligence Platform" })).toBeInTheDocument();
    const totalKpi = screen.getByText("Registered cameras").closest("article");
    expect(totalKpi).not.toBeNull();
    expect(await within(totalKpi!).findByText("0")).toBeInTheDocument();
    expect(await screen.findByText("No mapped cameras")).toBeInTheDocument();
    expect(screen.getByText("No offline or degraded assets")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Stream Federation" }));
    expect(await screen.findByRole("heading", { name: "Stream Federation" })).toBeInTheDocument();
    expect(await screen.findByText("No stream connections onboarded")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Live Operations" }));
    expect(await screen.findByRole("heading", { name: "Live Operations Matrix" })).toBeInTheDocument();
    expect(await screen.findByText("Onboard cameras in P01 before starting streams.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "GIS Operations" }));
    expect(await screen.findByRole("heading", { name: "GIS Operations" })).toBeInTheDocument();
    expect(screen.getByText("Route overlay ready")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Camera Registry" }));
    expect(await screen.findByRole("heading", { name: "Camera Registry" })).toBeInTheDocument();
    expect(await screen.findByText("No cameras found")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalled();
  });

  it("shows an operator-safe error state when the registry is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse({ detail: "backend trace must stay hidden" }, 503))));
    render(<App />);

    expect(await screen.findByText("Operational data is temporarily unavailable")).toBeInTheDocument();
    expect(screen.queryByText("backend trace must stay hidden")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /retry/i }).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByText("Registry API unavailable")).toBeInTheDocument());
  });

  it("renders KPI values returned by the registry instead of fabricated intelligence", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/departments")) return Promise.resolve(jsonResponse({ ...emptyPage, items: [{ id: "dept-1", code: "HOME", name: "Home Department" }], total: 1 }));
      if (url.includes("/cameras/statistics")) return Promise.resolve(jsonResponse({ ...emptyStats, total: 73, online: 68, offline: 3, degraded: 2, ai_enabled: 41 }));
      if (url.includes("/cameras/geojson")) return Promise.resolve(jsonResponse(emptyGeoJson));
      if (url.includes("/cameras")) return Promise.resolve(jsonResponse(emptyPage));
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    const totalKpi = screen.getByText("Registered cameras").closest("article");
    const onlineKpi = screen.getByText("Online cameras", { selector: ".command-kpi small" }).closest("article");
    const attentionKpi = screen.getByText("Health attention").closest("article");
    expect(await within(totalKpi!).findByText("73")).toBeInTheDocument();
    expect(within(attentionKpi!).getByText("5")).toBeInTheDocument();
    expect(within(onlineKpi!).getByText("68")).toBeInTheDocument();
    expect(screen.queryByText(/Vehicles detected today/i)).not.toBeInTheDocument();
    expect(screen.getByText("Presentation scenarios are explicitly disclosed.")).toBeInTheDocument();
  });
});
