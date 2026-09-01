import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StreamFederationPage } from "./StreamFederationPage";

const jsonResponse = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status,
  headers: { "Content-Type": "application/json" },
});

const adapter = {
  kind: "rtsp",
  label: "Direct RTSP",
  version: "1.0.0",
  schemes: ["rtsp"],
  capabilities: ["tcp_probe", "normalized_handoff"],
  supports_probe: true,
  supports_discovery: false,
  supports_stream_handoff: true,
  available: true,
  unavailable_reason: null,
};

const camera = {
  id: "camera-1",
  camera_uuid: "camera-1",
  camera_code: "HOME-AHD-001",
  camera_name: "Ashram Road Junction",
  department_id: "dept-1",
  district: "Ahmedabad",
  city: "Ahmedabad",
  latitude: 23.03,
  longitude: 72.58,
  camera_type: "anpr",
  connectivity_type: "fiber",
  stream_protocol: "rtsp",
  rtsp_capable: true,
  onvif_capable: false,
  status: "active",
  health: "online",
  storage_details: {},
  ai_capabilities: ["anpr"],
  ownership: "government",
  tags: [],
  created_at: "2026-08-24T10:00:00Z",
  updated_at: "2026-08-24T10:00:00Z",
};

const makeConnection = (status = "unverified", enabled = true) => ({
  id: "connection-1",
  camera_id: "camera-1",
  camera: {
    id: "camera-1",
    camera_code: "HOME-AHD-001",
    camera_name: "Ashram Road Junction",
    department_id: "dept-1",
    department_name: "Home Department",
    district: "Ahmedabad",
    city: "Ahmedabad",
    latitude: 23.03,
    longitude: 72.58,
  },
  name: "Primary evidence profile",
  adapter_kind: "rtsp",
  adapter_label: "Direct RTSP",
  stream_role: "primary",
  endpoint_display: "rtsp://edge-gateway.local:554/••••",
  endpoint_fingerprint: "abc123",
  has_credential_reference: true,
  enabled,
  priority: 100,
  verification_status: status,
  last_probe_at: status === "reachable" ? "2026-08-24T10:05:00Z" : null,
  last_probe_latency_ms: status === "reachable" ? 24 : null,
  last_error_code: null,
  last_error_message: null,
  last_success_at: status === "reachable" ? "2026-08-24T10:05:00Z" : null,
  failure_count: 0,
  normalized_metadata: status === "reachable" ? { transport: "tcp", endpoint_url: "rtsp://must-not-render/live" } : {},
  encryption_key_id: "key-1",
  created_by: "demo-operator",
  created_at: "2026-08-24T10:00:00Z",
  updated_at: "2026-08-24T10:05:00Z",
});

const statistics = {
  total: 11,
  enabled: 10,
  disabled: 1,
  by_status: { reachable: 7, unverified: 2, authentication_required: 1, disabled: 1 },
  by_adapter_kind: { rtsp: 11 },
  healthy_ratio: 0.64,
  last_probe_at: "2026-08-24T10:05:00Z",
};

const runtimeCapabilities = {
  available: true,
  binary_source: "configured",
  supported_adapter_kinds: ["rtsp"],
  unsupported_adapter_kinds: [],
  output_protocol: "hls",
  segment_duration_seconds: 2,
  playlist_window: 6,
  credential_resolver_mode: "reference_only",
  supervision: { watchdog_seconds: 8, max_backoff_seconds: 30 },
  boundary: "Browser media delivery only; AI inference is downstream.",
};

const makeRuntimeSession = (state = "live") => ({
  id: "runtime-session-1",
  connection_id: "connection-1",
  state,
  camera: {
    id: "camera-1",
    camera_code: "HOME-AHD-001",
    camera_name: "Ashram Road Junction",
    department_name: "Home Department",
    district: "Ahmedabad",
    city: "Ahmedabad",
  },
  profile: {
    id: "connection-1",
    name: "Primary evidence profile",
    adapter_kind: "rtsp",
    stream_role: "primary",
    endpoint_display: "rtsp://secured/••••",
  },
  playlist_url: "/api/v1/federation/runtime/media/runtime-session-1/index.m3u8",
  metrics: { frame: 120, fps: 24.8, out_time_ms: 5000, progress_at: "2026-08-24T10:06:00Z" },
  restart_count: state === "starting" ? 1 : 0,
  started_at: "2026-08-24T10:05:00Z",
  state_changed_at: "2026-08-24T10:06:00Z",
  last_progress_at: "2026-08-24T10:06:00Z",
  last_playlist_at: "2026-08-24T10:06:00Z",
  stopped_at: state === "stopped" ? "2026-08-24T10:07:00Z" : null,
  last_error_code: null,
  last_error_message: null,
  endpoint: "rtsp://operator:secret@camera.internal/live",
});

function createApi(options: { probeFails?: boolean; detailFails?: boolean; runtime?: boolean; initialRuntimeState?: string; runtimeStartFails?: boolean } = {}) {
  let connection = makeConnection();
  let runtimeSession = options.initialRuntimeState ? makeRuntimeSession(options.initialRuntimeState) : null;
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.includes("/federation/runtime/capabilities")) return Promise.resolve(jsonResponse(options.runtime ? runtimeCapabilities : { ...runtimeCapabilities, available: false, supported_adapter_kinds: [] }));
    if (url.endsWith("/federation/runtime/sessions") && method === "GET") return Promise.resolve(jsonResponse({ items: runtimeSession ? [runtimeSession] : [], total: runtimeSession ? 1 : 0 }));
    if (url.endsWith("/federation/connections/connection-1/runtime/start") && method === "POST") {
      if (options.runtimeStartFails) return Promise.resolve(jsonResponse({ detail: "rtsp://operator:secret@camera.internal/live backend trace" }, 503));
      runtimeSession = makeRuntimeSession("starting");
      return Promise.resolve(jsonResponse(runtimeSession));
    }
    if (url.endsWith("/federation/runtime/sessions/runtime-session-1") && method === "GET") {
      if (runtimeSession?.state === "starting") runtimeSession = makeRuntimeSession("live");
      return Promise.resolve(jsonResponse(runtimeSession));
    }
    if (url.endsWith("/federation/runtime/sessions/runtime-session-1/stop") && method === "POST") {
      runtimeSession = makeRuntimeSession("stopped");
      return Promise.resolve(jsonResponse(runtimeSession));
    }
    if (url.endsWith("/federation/runtime/sessions/runtime-session-1/restart") && method === "POST") {
      runtimeSession = makeRuntimeSession("starting");
      return Promise.resolve(jsonResponse(runtimeSession));
    }
    if (url.includes("/federation/adapters")) return Promise.resolve(jsonResponse({ items: [adapter] }));
    if (url.includes("/federation/connections/statistics")) return Promise.resolve(jsonResponse(statistics));
    if (url.includes("/federation/connections/connection-1/audit")) return Promise.resolve(jsonResponse({ items: [], total: 0, page: 1, page_size: 100, pages: 0 }));
    if (url.endsWith("/federation/connections/connection-1") && method === "GET") return Promise.resolve(options.detailFails
      ? jsonResponse({ detail: "temporarily unavailable" }, 503)
      : jsonResponse(connection));
    if (url.endsWith("/federation/connections/connection-1/probe") && method === "POST") {
      if (options.probeFails) return Promise.resolve(jsonResponse({ detail: "rtsp://secret.internal/live backend trace" }, 503));
      connection = makeConnection("reachable", connection.enabled);
      return Promise.resolve(jsonResponse(connection));
    }
    if (url.endsWith("/federation/connections/connection-1/disable") && method === "POST") {
      connection = makeConnection(connection.verification_status, false);
      return Promise.resolve(jsonResponse(connection));
    }
    if (url.endsWith("/federation/connections/connection-1/enable") && method === "POST") {
      connection = makeConnection(connection.verification_status, true);
      return Promise.resolve(jsonResponse(connection));
    }
    if (url.endsWith("/federation/connections") && method === "POST") {
      const unsafeResponse = { ...makeConnection(), endpoint: "rtsp://10.10.10.10:554/live" };
      connection = unsafeResponse;
      return Promise.resolve(jsonResponse(unsafeResponse));
    }
    if (url.includes("/federation/connections")) return Promise.resolve(jsonResponse({ items: [connection], total: 1, page: 1, page_size: 20, pages: 1 }));
    if (url.includes("/cameras")) return Promise.resolve(jsonResponse({ items: [camera], total: 1, page: 1, page_size: 50, pages: 1 }));
    return Promise.resolve(jsonResponse({}));
  });
  return fetchMock;
}

describe("P0.3 Stream Federation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders API-backed probe posture without fabricating active streams or edge readiness", async () => {
    vi.stubGlobal("fetch", createApi());
    render(<StreamFederationPage />);

    const profileKpi = (await screen.findByText("Connection profiles", { selector: ".federation-kpi small" })).closest("article");
    const reachableKpi = screen.getByText("Reachable probes").closest("article");
    const attentionKpi = screen.getByText("Needs attention").closest("article");
    const candidateKpi = screen.getByText("Candidate profiles").closest("article");
    expect(await within(profileKpi!).findByText("11")).toBeInTheDocument();
    expect(within(reachableKpi!).getByText("7")).toBeInTheDocument();
    expect(within(attentionKpi!).getByText("1")).toBeInTheDocument();
    expect(within(candidateKpi!).getByText("10")).toBeInTheDocument();
    expect(screen.queryByText(/active streams/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/edge.ready/i)).not.toBeInTheDocument();
    expect(screen.getByText(/sustained decode, FPS and frame quality are not yet verified/i)).toBeInTheDocument();
  });

  it("sends a strict onboarding payload, probes the saved profile, and removes the raw endpoint", async () => {
    const fetchMock = createApi();
    vi.stubGlobal("fetch", fetchMock);
    render(<StreamFederationPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Onboard connection" }));
    const cameraSelect = await screen.findByRole("combobox", { name: "Registered camera" });
    fireEvent.change(cameraSelect, { target: { value: "camera-1" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Profile name" }), { target: { value: "Analytics substream" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Source endpoint" }), { target: { value: "rtsp://10.10.10.10:554/live" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Opaque credential reference" }), { target: { value: "vault-ref:cctv/home/camera-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Encrypt and onboard" }));

    expect(await screen.findByText("Connection profile secured")).toBeInTheDocument();
    expect(await within(screen.getByRole("dialog")).findByText("Reachable")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("rtsp://10.10.10.10:554/live")).not.toBeInTheDocument();
    expect(screen.queryByText("rtsp://10.10.10.10:554/live")).not.toBeInTheDocument();

    const createCall = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith("/federation/connections") && init?.method === "POST");
    expect(createCall).toBeDefined();
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      camera_id: "camera-1",
      name: "Analytics substream",
      adapter_kind: "rtsp",
      endpoint: "rtsp://10.10.10.10:554/live",
      stream_role: "primary",
      credential_reference: "vault-ref:cctv/home/camera-1",
      priority: 100,
      enabled: true,
    });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/connection-1/probe"), expect.objectContaining({ method: "POST" }));
  });

  it("applies server-side filters, transitions probe status, and confirms disabling", async () => {
    const fetchMock = createApi();
    vi.stubGlobal("fetch", fetchMock);
    render(<StreamFederationPage />);

    await screen.findByText("Primary evidence profile");
    fireEvent.change(screen.getByRole("combobox", { name: "Adapter filter" }), { target: { value: "rtsp" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Verification filter" }), { target: { value: "unverified" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Activation filter" }), { target: { value: "true" } });
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => {
      const url = String(input);
      return url.includes("adapter_kind=rtsp") && url.includes("verification_status=unverified") && url.includes("enabled=true");
    })).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "Probe Primary evidence profile" }));
    expect(await screen.findByText("Reachable", { selector: ".federation-status span" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Disable Primary evidence profile" }));
    expect(screen.getByRole("heading", { name: "Disable connection profile" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Disable profile" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith("/connection-1/disable") && init?.method === "POST")).toBe(true));
  });

  it("surfaces an operator-safe 5xx probe error without leaking backend details", async () => {
    vi.stubGlobal("fetch", createApi({ probeFails: true }));
    render(<StreamFederationPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Probe Primary evidence profile" }));
    expect(await screen.findByText("Operation did not complete")).toBeInTheDocument();
    expect(screen.getByText(/temporarily unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/secret\.internal|backend trace/i)).not.toBeInTheDocument();
  });

  it("keeps camera details available when the authoritative refresh is unavailable", async () => {
    vi.stubGlobal("fetch", createApi({ detailFails: true, runtime: true, initialRuntimeState: "live" }));
    render(<StreamFederationPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Open Primary evidence profile details" }));

    const drawer = await screen.findByRole("complementary", { name: "Connection details" });
    expect(within(drawer).getAllByText("Ashram Road Junction").length).toBeGreaterThan(0);
    expect(within(drawer).getAllByText("HOME-AHD-001").length).toBeGreaterThan(0);
    expect(await within(drawer).findByText(/latest profile already loaded/i)).toBeInTheDocument();
  });

  it("starts a supervised session, transitions to live, and mounts the allowlisted HLS player", async () => {
    const fetchMock = createApi({ runtime: true });
    vi.stubGlobal("fetch", fetchMock);
    render(<StreamFederationPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Start live view for Primary evidence profile" }));

    expect(await screen.findByRole("complementary", { name: "Live media runtime" })).toBeInTheDocument();
    expect(await screen.findByLabelText("Live media for Ashram Road Junction")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/connections/connection-1/runtime/start"), expect.objectContaining({ method: "POST" }));
    expect(screen.getByText("Browser delivery is not AI inference")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("operator:secret@camera.internal");
  });

  it("stops and restarts an existing runtime through explicit profile controls", async () => {
    const fetchMock = createApi({ runtime: true, initialRuntimeState: "live" });
    vi.stubGlobal("fetch", fetchMock);
    render(<StreamFederationPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Stop live runtime for Primary evidence profile" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith("/runtime-session-1/stop") && init?.method === "POST")).toBe(true));
    expect(await screen.findByText("Stopped", { selector: ".runtime-status span" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Restart live runtime for Primary evidence profile" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith("/runtime-session-1/restart") && init?.method === "POST")).toBe(true));
    expect(await screen.findByRole("complementary", { name: "Live media runtime" })).toBeInTheDocument();
  });

  it("surfaces a safe runtime 5xx without rendering source details", async () => {
    vi.stubGlobal("fetch", createApi({ runtime: true, runtimeStartFails: true }));
    render(<StreamFederationPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Start live view for Primary evidence profile" }));
    expect(await screen.findByText("Media runtime operation did not complete")).toBeInTheDocument();
    expect(screen.getByText(/temporarily unavailable/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/operator:secret|camera\.internal|backend trace/i);
  });
});
