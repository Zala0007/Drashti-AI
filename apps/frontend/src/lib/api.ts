import type {
  AuditEntry,
  Camera,
  CameraCreate,
  CameraFilters,
  CameraFilterOptions,
  CameraGeoJson,
  CameraStatistics,
  Department,
  DepartmentCreate,
  ImportResult,
  Page,
} from "../types/registry";
import type {
  FederationAdapter,
  FederationAdapterCatalog,
  FederationAuditEntry,
  FederationConnection,
  FederationConnectionCreate,
  FederationConnectionFilters,
  FederationConnectionPage,
  FederationConnectionPatch,
  GovernmentFeedCatalogue,
  GovernmentFeedSyncResult,
  FederationStatistics,
  CredentialProfile,
  CredentialProfileCreate,
  CredentialProfilePage,
  CredentialProfilePatch,
  RuntimeCapabilities,
  RuntimeSession,
  RuntimeSessionList,
} from "../types/federation";
import { safeRuntimePlaylistUrl } from "./federation";
import type {
  AnalyticsCapabilities,
  CameraAnalyticsList,
  ProcessingStreamSession,
  ProcessingStreamSessionList,
  ProcessingStreamStart,
  StreamAggregateMetrics,
  StreamCapabilities,
} from "../types/streams";
import type {
  InvestigationCase,
  InvestigationCreate,
  InvestigationWorkspace,
  PredictionBacktest,
} from "../types/investigation";
import type {
  CaseFile,
  CaseWorkspace,
  CoverageAnalysis,
  CoverageWhatIf,
  HealthDashboard,
  HealthHistory,
  ReIDMatch,
  ReIDResult,
} from "../types/advanced";
import type {
  AIDetection,
  AIPage,
  AIPlateDetection,
  AIShowcaseOverview,
} from "../types/ai";
import type {
  VisualIntelligenceStatus,
  VisualQueueResponse,
  VisualSearchFilters,
  VisualSearchResponse,
} from "../types/visualIntelligence";
import type {
  WatchlistAlert,
  WatchlistAlertList,
  WatchlistDashboard,
  WatchlistEntry,
  WatchlistEntryList,
} from "../types/watchlist";

const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim();
export const API_BASE_URL = (configuredBase || "/api/v1").replace(/\/$/, "");

export function apiMediaUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const apiMarker = "/api/v1";
  const origin = API_BASE_URL.endsWith(apiMarker)
    ? API_BASE_URL.slice(0, -apiMarker.length)
    : API_BASE_URL;
  return `${origin}${path.startsWith("/") ? path : `/${path}`}`;
}

export class ApiError extends Error {
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

const errorMessage = (body: unknown, fallback: string): string => {
  if (typeof body === "string" && body.trim()) return body;
  if (body && typeof body === "object") {
    const candidate = body as { detail?: unknown; message?: unknown; error?: unknown };
    if (candidate.error && typeof candidate.error === "object") {
      const nested = candidate.error as { message?: unknown };
      if (typeof nested.message === "string") return nested.message;
    }
    if (typeof candidate.detail === "string") return candidate.detail;
    if (typeof candidate.message === "string") return candidate.message;
    if (Array.isArray(candidate.detail)) {
      return candidate.detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return String(item);
        })
        .join("; ");
    }
  }
  return fallback;
};

async function request<T>(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", "application/json");

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      credentials: "same-origin",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("Platform API is unreachable. Check the service connection.", 0, error);
  }

  const contentType = response.headers.get("content-type") ?? "";
  const body: unknown = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    if (response.status >= 500) {
      throw new ApiError(
        "Platform service is temporarily unavailable. Retry or contact the platform administrator.",
        response.status,
        body,
      );
    }
    throw new ApiError(
      errorMessage(body, `Request failed with status ${response.status}`),
      response.status,
      body,
    );
  }
  return body as T;
}

const queryString = (values: Record<string, string | number | boolean | undefined>): string => {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
};

const listItems = <T>(value: Page<T> | T[]): T[] => (Array.isArray(value) ? value : value.items);

export const registryApi = {
  async departments(signal?: AbortSignal): Promise<Department[]> {
    const data = await request<Page<Department> | Department[]>("/departments?page_size=100", {}, signal);
    return listItems(data);
  },

  createDepartment(payload: DepartmentCreate): Promise<Department> {
    return request("/departments", { method: "POST", body: JSON.stringify(payload) });
  },

  cameras(
    filters: CameraFilters,
    page: number,
    pageSize: number,
    signal?: AbortSignal,
  ): Promise<Page<Camera>> {
    return request(
      `/cameras${queryString({
        search: filters.search.trim(),
        department_id: filters.department_id,
        district: filters.district.trim(),
        city: filters.city.trim(),
        vendor: filters.vendor.trim(),
        vms: filters.vms.trim(),
        status: filters.status,
        health: filters.health,
        ai_capability: filters.ai_capability,
        include_retired: filters.status === "retired" ? true : undefined,
        page,
        page_size: pageSize,
      })}`,
      {},
      signal,
    );
  },

  camera(id: string, signal?: AbortSignal): Promise<Camera> {
    return request(`/cameras/${encodeURIComponent(id)}`, {}, signal);
  },

  filterOptions(signal?: AbortSignal): Promise<CameraFilterOptions> {
    return request("/cameras/filter-options", {}, signal);
  },

  createCamera(payload: CameraCreate): Promise<Camera> {
    return request("/cameras", { method: "POST", body: JSON.stringify(payload) });
  },

  statistics(filters: CameraFilters, signal?: AbortSignal): Promise<CameraStatistics> {
    return request(
      `/cameras/statistics${queryString({
        search: filters.search.trim(),
        department_id: filters.department_id,
        district: filters.district.trim(),
        city: filters.city.trim(),
        vendor: filters.vendor.trim(),
        vms: filters.vms.trim(),
        status: filters.status,
        health: filters.health,
        ai_capability: filters.ai_capability,
        include_retired: filters.status === "retired" ? true : undefined,
      })}`,
      {},
      signal,
    );
  },

  geoJson(filters: CameraFilters, signal?: AbortSignal): Promise<CameraGeoJson> {
    return request(
      `/cameras/geojson${queryString({
        search: filters.search.trim(),
        department_id: filters.department_id,
        district: filters.district.trim(),
        city: filters.city.trim(),
        vendor: filters.vendor.trim(),
        vms: filters.vms.trim(),
        status: filters.status,
        health: filters.health,
        ai_capability: filters.ai_capability,
        include_retired: filters.status === "retired" ? true : undefined,
      })}`,
      {},
      signal,
    );
  },

  audit(id: string, signal?: AbortSignal): Promise<AuditEntry[]> {
    return request<Page<AuditEntry> | AuditEntry[]>(
      `/cameras/${encodeURIComponent(id)}/audit?page_size=100`,
      {},
      signal,
    ).then(listItems);
  },

  importCsv(file: File): Promise<ImportResult> {
    const body = new FormData();
    body.append("file", file);
    return request("/cameras/import", { method: "POST", body });
  },
};

type RawFederationAdapter = FederationAdapter & {
  supports_probe?: boolean;
  supports_discovery?: boolean;
  supports_stream_handoff?: boolean;
  available?: boolean;
  unavailable_reason?: string | null;
};

type RawFederationConnection = Omit<FederationConnection, "camera_code" | "camera_name"> & {
  camera_code?: string;
  camera_name?: string;
};

type RawFederationStatistics = Partial<FederationStatistics> & {
  total: number;
  enabled: number;
  disabled?: number;
  by_status?: Record<string, number>;
  by_adapter_kind?: Record<string, number>;
  healthy_ratio?: number;
  last_probe_at?: string | null;
};

const normalizeAdapter = (adapter: RawFederationAdapter): FederationAdapter => ({
  ...adapter,
  description: adapter.description || `${adapter.label} connection-profile adapter. Runtime capabilities are declared by this manifest.`,
  probe_supported: adapter.probe_supported ?? adapter.supports_probe ?? false,
  discovery_supported: adapter.discovery_supported ?? adapter.supports_discovery ?? false,
  stream_handoff_supported: adapter.stream_handoff_supported ?? adapter.supports_stream_handoff ?? false,
  availability: adapter.availability ?? (adapter.available === false ? "unavailable" : "available"),
  availability_message: adapter.availability_message ?? adapter.unavailable_reason,
});

const adapterItems = (value: FederationAdapterCatalog | RawFederationAdapter[]): FederationAdapter[] =>
  (Array.isArray(value) ? value : Array.isArray(value.items) ? value.items : []).map(normalizeAdapter);

const normalizeConnection = (connection: RawFederationConnection): FederationConnection => {
  const safe = { ...connection } as RawFederationConnection & Record<string, unknown>;
  delete safe.endpoint;
  delete safe.endpoint_ciphertext;
  delete safe.credential_reference;
  return {
    ...safe,
    camera_id: connection.camera_id ?? connection.camera?.id ?? "",
    camera_code: connection.camera_code ?? connection.camera?.camera_code ?? "Unassigned",
    camera_name: connection.camera_name ?? connection.camera?.camera_name ?? "Unknown camera",
    department_name: connection.department_name ?? connection.camera?.department_name,
    district: connection.district ?? connection.camera?.district,
    city: connection.city ?? connection.camera?.city,
  } as FederationConnection;
};

const countStatuses = (values: Record<string, number>, names: string[]): number =>
  Object.entries(values).reduce(
    (sum, [status, count]) => {
      const normalized = status.toLowerCase().replace(/[ .-]+/g, "_");
      const matched = names.some((name) => normalized === name || normalized.startsWith(`${name}_`) || normalized.endsWith(`_${name}`));
      return matched ? sum + count : sum;
    },
    0,
  );

const normalizeStatistics = (statistics: RawFederationStatistics): FederationStatistics => {
  const byStatus = statistics.by_status ?? {};
  const reachable = statistics.reachable ?? countStatuses(byStatus, ["reachable", "verified", "healthy", "ready"]);
  const unverified = statistics.unverified ?? countStatuses(byStatus, ["unverified", "pending", "unknown", "not_tested"]);
  const explicitAttention = countStatuses(byStatus, ["unreachable", "failed", "error", "degraded", "authentication_required", "blocked", "misconfigured", "adapter_unavailable"]);
  const attention = statistics.attention ?? explicitAttention;
  return {
    total: statistics.total,
    enabled: statistics.enabled,
    disabled: statistics.disabled,
    reachable,
    attention,
    unverified,
    by_status: byStatus,
    by_adapter: statistics.by_adapter ?? statistics.by_adapter_kind ?? {},
    healthy_ratio: statistics.healthy_ratio,
    last_probe_at: statistics.last_probe_at,
  };
};

const normalizeRuntimeSession = (session: RuntimeSession): RuntimeSession => ({
  id: session.id,
  connection_id: session.connection_id,
  state: session.state,
  camera: {
    id: session.camera?.id ?? "",
    camera_code: session.camera?.camera_code ?? "Unassigned",
    camera_name: session.camera?.camera_name ?? "Unknown camera",
    department_name: session.camera?.department_name,
    district: session.camera?.district,
    city: session.camera?.city,
  },
  profile: {
    id: session.profile?.id ?? session.connection_id,
    name: session.profile?.name ?? "Runtime profile",
    adapter_kind: session.profile?.adapter_kind ?? "unknown",
    stream_role: session.profile?.stream_role ?? "primary",
    endpoint_display: session.profile?.endpoint_display,
  },
  playlist_url: safeRuntimePlaylistUrl(session.playlist_url),
  metrics: {
    frame: session.metrics?.frame,
    fps: session.metrics?.fps,
    out_time_ms: session.metrics?.out_time_ms,
    progress_at: session.metrics?.progress_at,
  },
  restart_count: session.restart_count ?? 0,
  started_at: session.started_at,
  state_changed_at: session.state_changed_at,
  last_progress_at: session.last_progress_at,
  last_playlist_at: session.last_playlist_at,
  stopped_at: session.stopped_at,
  last_error_code: session.last_error_code,
  last_error_message: session.last_error_message && /:\/\//.test(session.last_error_message)
    ? "Runtime source details were redacted."
    : session.last_error_message,
});

const normalizeRuntimeCapabilities = (capabilities: Partial<RuntimeCapabilities>): RuntimeCapabilities => ({
  available: Boolean(capabilities.available),
  binary_source: capabilities.binary_source ?? "unavailable",
  supported_adapter_kinds: capabilities.supported_adapter_kinds ?? [],
  unsupported_adapter_kinds: capabilities.unsupported_adapter_kinds ?? [],
  output_protocol: capabilities.output_protocol ?? "unavailable",
  segment_duration_seconds: capabilities.segment_duration_seconds ?? 0,
  playlist_window: capabilities.playlist_window ?? 0,
  credential_resolver_mode: capabilities.credential_resolver_mode ?? "unavailable",
  supervision: {
    watchdog_seconds: capabilities.supervision?.watchdog_seconds ?? 0,
    max_backoff_seconds: capabilities.supervision?.max_backoff_seconds ?? 0,
  },
  boundary: capabilities.boundary ?? "Browser delivery only; AI inference remains downstream.",
});

export const federationApi = {
  governmentFeedCatalogue(signal?: AbortSignal): Promise<GovernmentFeedCatalogue> {
    return request<GovernmentFeedCatalogue>(
      "/federation/catalogues/government-feeds",
      {},
      signal,
    );
  },

  syncGovernmentFeeds(): Promise<GovernmentFeedSyncResult> {
    return request<GovernmentFeedSyncResult>(
      "/federation/catalogues/government-feeds/sync",
      {
        method: "POST",
        body: JSON.stringify({ include_offline: true, create_hls_fallback: true }),
      },
    );
  },

  adapters(signal?: AbortSignal): Promise<FederationAdapter[]> {
    return request<FederationAdapterCatalog | RawFederationAdapter[]>("/federation/adapters", {}, signal)
      .then(adapterItems);
  },

  connections(
    filters: FederationConnectionFilters,
    page: number,
    pageSize: number,
    signal?: AbortSignal,
  ): Promise<FederationConnectionPage> {
    return request<FederationConnectionPage>(
      `/federation/connections${queryString({
        search: filters.search.trim(),
        camera_id: filters.camera_id,
        adapter_kind: filters.adapter_kind,
        verification_status: filters.verification_status,
        enabled: filters.enabled === "" ? undefined : filters.enabled,
        page,
        page_size: pageSize,
      })}`,
      {},
      signal,
    ).then((result) => ({ ...result, items: result.items.map((item) => normalizeConnection(item)) }));
  },

  statistics(signal?: AbortSignal): Promise<FederationStatistics> {
    return request<RawFederationStatistics>("/federation/connections/statistics", {}, signal)
      .then(normalizeStatistics);
  },

  connection(id: string, signal?: AbortSignal): Promise<FederationConnection> {
    return request<RawFederationConnection>(`/federation/connections/${encodeURIComponent(id)}`, {}, signal)
      .then(normalizeConnection);
  },

  createConnection(payload: FederationConnectionCreate): Promise<FederationConnection> {
    return request<RawFederationConnection>("/federation/connections", { method: "POST", body: JSON.stringify(payload) })
      .then(normalizeConnection);
  },

  patchConnection(id: string, payload: FederationConnectionPatch): Promise<FederationConnection> {
    return request<RawFederationConnection>(`/federation/connections/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }).then(normalizeConnection);
  },

  probe(id: string): Promise<FederationConnection> {
    return request<RawFederationConnection>(`/federation/connections/${encodeURIComponent(id)}/probe`, { method: "POST" })
      .then(normalizeConnection);
  },

  enable(id: string): Promise<FederationConnection> {
    return request<RawFederationConnection>(`/federation/connections/${encodeURIComponent(id)}/enable`, { method: "POST" })
      .then(normalizeConnection);
  },

  disable(id: string): Promise<FederationConnection> {
    return request<RawFederationConnection>(`/federation/connections/${encodeURIComponent(id)}/disable`, { method: "POST" })
      .then(normalizeConnection);
  },

  audit(id: string, signal?: AbortSignal): Promise<FederationAuditEntry[]> {
    return request<Page<FederationAuditEntry> | FederationAuditEntry[]>(
      `/federation/connections/${encodeURIComponent(id)}/audit?page_size=100`,
      {},
      signal,
    ).then(listItems);
  },

  credentials(
    filters: { department_id?: string; enabled?: boolean; search?: string } = {},
    signal?: AbortSignal,
  ): Promise<CredentialProfilePage> {
    return request<Partial<CredentialProfilePage>>(
      `/federation/credentials${queryString({
        department_id: filters.department_id,
        enabled: filters.enabled,
        search: filters.search?.trim(),
        page_size: 200,
      })}`,
      {},
      signal,
    ).then((result) => ({
      items: Array.isArray(result.items) ? result.items : [],
      total: result.total ?? 0,
      page: result.page ?? 1,
      page_size: result.page_size ?? 200,
      pages: result.pages ?? 0,
    }));
  },

  createCredential(payload: CredentialProfileCreate): Promise<CredentialProfile> {
    return request<CredentialProfile>("/federation/credentials", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  patchCredential(id: string, payload: CredentialProfilePatch): Promise<CredentialProfile> {
    return request<CredentialProfile>(`/federation/credentials/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  runtimeCapabilities(signal?: AbortSignal): Promise<RuntimeCapabilities> {
    return request<Partial<RuntimeCapabilities>>("/federation/runtime/capabilities", {}, signal)
      .then(normalizeRuntimeCapabilities);
  },

  runtimeSessions(signal?: AbortSignal): Promise<RuntimeSessionList> {
    return request<RuntimeSessionList>("/federation/runtime/sessions", {}, signal)
      .then((result) => ({ ...result, items: (result.items ?? []).map(normalizeRuntimeSession) }));
  },

  startRuntime(connectionId: string): Promise<RuntimeSession> {
    return request<RuntimeSession>(
      `/federation/connections/${encodeURIComponent(connectionId)}/runtime/start`,
      { method: "POST" },
    ).then(normalizeRuntimeSession);
  },

  runtimeSession(sessionId: string, signal?: AbortSignal): Promise<RuntimeSession> {
    return request<RuntimeSession>(`/federation/runtime/sessions/${encodeURIComponent(sessionId)}`, {}, signal)
      .then(normalizeRuntimeSession);
  },

  stopRuntime(sessionId: string): Promise<RuntimeSession> {
    return request<RuntimeSession>(`/federation/runtime/sessions/${encodeURIComponent(sessionId)}/stop`, { method: "POST" })
      .then(normalizeRuntimeSession);
  },

  restartRuntime(sessionId: string): Promise<RuntimeSession> {
    return request<RuntimeSession>(`/federation/runtime/sessions/${encodeURIComponent(sessionId)}/restart`, { method: "POST" })
      .then(normalizeRuntimeSession);
  },
};

export const streamApi = {
  sessions(signal?: AbortSignal): Promise<ProcessingStreamSessionList> {
    return request<ProcessingStreamSessionList>("/streams", {}, signal);
  },

  metrics(signal?: AbortSignal): Promise<StreamAggregateMetrics> {
    return request<StreamAggregateMetrics>("/streams/metrics", {}, signal);
  },

  capabilities(signal?: AbortSignal): Promise<StreamCapabilities> {
    return request<StreamCapabilities>("/streams/capabilities", {}, signal);
  },

  analyticsCapabilities(signal?: AbortSignal): Promise<AnalyticsCapabilities> {
    return request<AnalyticsCapabilities>("/streams/analytics/capabilities", {}, signal);
  },

  analytics(signal?: AbortSignal): Promise<CameraAnalyticsList> {
    return request<CameraAnalyticsList>("/streams/analytics", {}, signal);
  },

  health(cameraId: string, signal?: AbortSignal): Promise<ProcessingStreamSession> {
    return request<ProcessingStreamSession>(
      `/streams/${encodeURIComponent(cameraId)}/health`,
      {},
      signal,
    );
  },

  start(
    cameraId: string,
    payload: ProcessingStreamStart = {},
    signal?: AbortSignal,
  ): Promise<ProcessingStreamSession> {
    return request<ProcessingStreamSession>(
      `/streams/${encodeURIComponent(cameraId)}/start`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      signal,
    );
  },

  stop(cameraId: string): Promise<ProcessingStreamSession> {
    return request<ProcessingStreamSession>(`/streams/${encodeURIComponent(cameraId)}/stop`, {
      method: "POST",
    });
  },

  restart(cameraId: string, payload: ProcessingStreamStart = {}): Promise<ProcessingStreamSession> {
    return request<ProcessingStreamSession>(`/streams/${encodeURIComponent(cameraId)}/restart`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  previewUrl(cameraId: string, generation: string): string {
    return `${API_BASE_URL}/streams/${encodeURIComponent(cameraId)}/preview.jpg?v=${encodeURIComponent(generation)}`;
  },
};

const investigationHeaders = {
  "X-Actor-ID": "demo-investigator",
  "X-Actor-Role": "investigator",
};

export const investigationApi = {
  list(signal?: AbortSignal): Promise<{ items: InvestigationCase[]; total: number }> {
    return request("/investigations", { headers: investigationHeaders }, signal);
  },

  workspace(id: string, signal?: AbortSignal): Promise<InvestigationWorkspace> {
    return request(
      `/investigations/${encodeURIComponent(id)}`,
      { headers: investigationHeaders },
      signal,
    );
  },

  predictionBacktest(id: string, signal?: AbortSignal): Promise<PredictionBacktest> {
    return request(
      `/investigations/${encodeURIComponent(id)}/prediction-backtest`,
      { headers: investigationHeaders },
      signal,
    );
  },

  create(payload: InvestigationCreate): Promise<InvestigationWorkspace> {
    return request("/investigations", {
      method: "POST",
      headers: investigationHeaders,
      body: JSON.stringify(payload),
    });
  },

  seedDemo(targetPlate = "GJ01AB1234"): Promise<{
    target_plate: string;
    events_created: number;
    cameras_used: number;
    disclosure: string;
  }> {
    return request("/investigations/demo-scenario", {
      method: "POST",
      headers: investigationHeaders,
      body: JSON.stringify({ target_plate: targetPlate }),
    });
  },

  transition(
    id: string,
    status: "suspended" | "completed" | "cancelled" | "active_tracking",
    reason: string,
  ): Promise<InvestigationWorkspace> {
    return request(`/investigations/${encodeURIComponent(id)}/transition`, {
      method: "POST",
      headers: investigationHeaders,
      body: JSON.stringify({ status, reason }),
    });
  },
};

const operationsHeaders = {
  "X-Actor-ID": "demo-operations",
  "X-Actor-Role": "operations",
};
const plannerHeaders = {
  "X-Actor-ID": "demo-planner",
  "X-Actor-Role": "planner",
};

export const advancedApi = {
  rankReID(investigationId: string): Promise<ReIDResult> {
    return request(`/reid/investigations/${encodeURIComponent(investigationId)}/rank`, {
      method: "POST",
      headers: investigationHeaders,
      body: JSON.stringify({ max_candidates: 20 }),
    });
  },
  seedReIDDemo(investigationId: string): Promise<{ observations_created: number; disclosure: string }> {
    return request(`/reid/investigations/${encodeURIComponent(investigationId)}/demo`, {
      method: "POST",
      headers: investigationHeaders,
    });
  },
  reviewReID(matchId: string, status: "confirmed" | "rejected" | "candidate", note: string): Promise<ReIDMatch> {
    return request(`/reid/matches/${encodeURIComponent(matchId)}/review`, {
      method: "POST",
      headers: investigationHeaders,
      body: JSON.stringify({ status, note }),
    });
  },
  cases(signal?: AbortSignal): Promise<{ items: CaseFile[]; total: number }> {
    return request("/cases?page_size=100", { headers: investigationHeaders }, signal);
  },
  caseWorkspace(id: string, signal?: AbortSignal): Promise<CaseWorkspace> {
    return request(`/cases/${encodeURIComponent(id)}`, { headers: investigationHeaders }, signal);
  },
  createCase(payload: {
    title: string;
    description: string;
    priority: string;
    authorization_reference: string;
    investigation_id?: string;
  }): Promise<CaseWorkspace> {
    return request("/cases", {
      method: "POST",
      headers: investigationHeaders,
      body: JSON.stringify(payload),
    });
  },
  exportCase(id: string): Promise<{ integrity_disclosure: string; workspace: CaseWorkspace }> {
    return request(`/cases/${encodeURIComponent(id)}/export`, {
      method: "POST",
      headers: investigationHeaders,
    });
  },
  health(signal?: AbortSignal): Promise<HealthDashboard> {
    return request("/camera-health/dashboard", { headers: operationsHeaders }, signal);
  },
  captureHealth(): Promise<HealthDashboard> {
    return request("/camera-health/snapshot", { method: "POST", headers: operationsHeaders });
  },
  healthHistory(cameraId: string, signal?: AbortSignal): Promise<HealthHistory> {
    return request(
      `/camera-health/cameras/${encodeURIComponent(cameraId)}/history`,
      { headers: operationsHeaders },
      signal,
    );
  },
  coverage(signal?: AbortSignal): Promise<CoverageAnalysis> {
    return request("/coverage/latest", { headers: plannerHeaders }, signal);
  },
  analyzeCoverage(): Promise<CoverageAnalysis> {
    return request("/coverage/analyses", {
      method: "POST",
      headers: plannerHeaders,
      body: JSON.stringify({}),
    });
  },
  coverageWhatIf(cameraId: string): Promise<CoverageWhatIf> {
    return request("/coverage/what-if", {
      method: "POST",
      headers: plannerHeaders,
      body: JSON.stringify({ camera_id: cameraId }),
    });
  },
};

export const aiApi = {
  overview(signal?: AbortSignal): Promise<AIShowcaseOverview> {
    return request("/ai/overview", {}, signal);
  },
  detections(
    filters: {
      query?: string;
      className?: string;
      minimumConfidence?: number;
      page?: number;
      pageSize?: number;
    },
    signal?: AbortSignal,
  ): Promise<AIPage<AIDetection>> {
    const params = new URLSearchParams();
    if (filters.query?.trim()) params.set("query", filters.query.trim());
    if (filters.className) params.set("class_name", filters.className);
    params.set("minimum_confidence", String(filters.minimumConfidence ?? 0.4));
    params.set("page", String(filters.page ?? 1));
    params.set("page_size", String(filters.pageSize ?? 24));
    return request(`/ai/detections?${params}`, {}, signal);
  },
  plates(
    filters: { query?: string; page?: number; pageSize?: number },
    signal?: AbortSignal,
  ): Promise<AIPage<AIPlateDetection>> {
    const params = new URLSearchParams();
    if (filters.query?.trim()) params.set("query", filters.query.trim());
    params.set("page", String(filters.page ?? 1));
    params.set("page_size", String(filters.pageSize ?? 18));
    return request(`/ai/plates?${params}`, {}, signal);
  },
};

export const watchlistApi = {
  dashboard(signal?: AbortSignal): Promise<WatchlistDashboard> {
    return request("/watchlist/dashboard", { headers: operationsHeaders }, signal);
  },
  entries(signal?: AbortSignal): Promise<WatchlistEntryList> {
    return request("/watchlist/entries", { headers: operationsHeaders }, signal);
  },
  createEntry(payload: {
    plate_text: string;
    subject_label: string;
    reason: string;
    severity: "critical" | "high" | "standard";
  }): Promise<WatchlistEntry> {
    return request("/watchlist/entries", {
      method: "POST",
      headers: operationsHeaders,
      body: JSON.stringify(payload),
    });
  },
  updateEntry(id: string, status: "active" | "inactive"): Promise<WatchlistEntry> {
    return request(`/watchlist/entries/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: operationsHeaders,
      body: JSON.stringify({ status }),
    });
  },
  alerts(signal?: AbortSignal): Promise<WatchlistAlertList> {
    return request("/watchlist/alerts", { headers: operationsHeaders }, signal);
  },
  reviewAlert(
    id: string,
    status: "acknowledged" | "resolved" | "false_positive",
  ): Promise<WatchlistAlert> {
    return request(`/watchlist/alerts/${encodeURIComponent(id)}/review`, {
      method: "POST",
      headers: operationsHeaders,
      body: JSON.stringify({ status }),
    });
  },
};

export const visualIntelligenceApi = {
  status(signal?: AbortSignal): Promise<VisualIntelligenceStatus> {
    return request("/visual-intelligence/status", { headers: investigationHeaders }, signal);
  },
  search(
    query: string,
    filters: VisualSearchFilters = {},
    page = 1,
    pageSize = 18,
    signal?: AbortSignal,
  ): Promise<VisualSearchResponse> {
    return request("/visual-intelligence/search", {
      method: "POST",
      headers: investigationHeaders,
      body: JSON.stringify({ query, filters, page, page_size: pageSize }),
    }, signal);
  },
  backfill(limit = 12, retryFailed = false): Promise<VisualQueueResponse> {
    return request("/visual-intelligence/backfill", {
      method: "POST",
      headers: investigationHeaders,
      body: JSON.stringify({ limit, retry_failed: retryFailed }),
    });
  },
};
