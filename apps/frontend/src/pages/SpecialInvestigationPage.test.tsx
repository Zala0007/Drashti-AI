import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SpecialInvestigationPage } from "./SpecialInvestigationPage";

vi.mock("leaflet", () => ({ default: { divIcon: (options: unknown) => options } }));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="investigation-map">{children}</div>,
  TileLayer: () => null,
  Marker: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  CircleMarker: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Polyline: () => <div data-testid="route-segment" />,
  Tooltip: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  useMap: () => ({ setView: vi.fn(), fitBounds: vi.fn() }),
}));

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "Content-Type": "application/json" },
});

const camera = (id: string, code: string, latitude: number, longitude: number) => ({
  id,
  camera_code: code,
  camera_name: `${code} Junction`,
  district: "Ahmedabad",
  city: "Ahmedabad",
  location_description: "Controlled demo corridor",
  latitude,
  longitude,
  bearing_degrees: 45,
  health: "online",
  status: "active",
  ai_enabled: true,
  ai_capabilities: ["anpr"],
});

const activeCase = {
  id: "case-1",
  case_number: "INV-2026-A1B2C3",
  target_plate: "GJ01AB1234",
  target_plate_original: "GJ01AB1234",
  priority: "high",
  reason: "Authorized pursuit demonstration",
  district: null,
  status: "active_tracking",
  created_by: "demo-investigator",
  started_at: "2026-08-29T10:00:00Z",
  ended_at: null,
  latest_camera_id: "camera-2",
  graph_method: "geospatial_directional_fallback",
  route_confidence: "high",
  last_recalculated_at: "2026-08-29T10:09:00Z",
  created_at: "2026-08-29T10:00:00Z",
  updated_at: "2026-08-29T10:09:00Z",
};

const workspace = {
  case: activeCase,
  observations: [
    {
      id: "observation-1",
      event: { id: "event-1", source_event_id: "demo-1", observed_at: "2026-08-29T10:01:00Z", plate_text: "GJ01AB1234", normalized_plate: "GJ01AB1234", plate_confidence: 0.98, direction: "north-east", vehicle_attributes: {}, evidence_reference: "demo-evidence:1", model_version: "demo-v1", source: "demonstration_scenario" },
      camera: camera("camera-1", "CAM-AHD-007", 23.03, 72.57),
      plate_similarity: 1,
      temporal_feasibility: 1,
      route_feasibility: 1,
      correlation_score: 0.98,
      status: "confirmed",
      reasoning: ["exact normalized plate", "elapsed time feasible"],
      evidence_class: "observed",
    },
    {
      id: "observation-2",
      event: { id: "event-2", source_event_id: "demo-2", observed_at: "2026-08-29T10:08:00Z", plate_text: "GJ01A81234", normalized_plate: "GJ01A81234", plate_confidence: 0.88, direction: "north-east", vehicle_attributes: {}, evidence_reference: "demo-evidence:2", model_version: "demo-v1", source: "demonstration_scenario" },
      camera: camera("camera-2", "CAM-AHD-014", 23.04, 72.58),
      plate_similarity: 0.975,
      temporal_feasibility: 1,
      route_feasibility: 1,
      correlation_score: 0.91,
      status: "confirmed",
      reasoning: ["controlled OCR confusion", "elapsed time feasible"],
      evidence_class: "observed",
    },
  ],
  candidates: [{ id: "candidate-1", camera: camera("camera-3", "CAM-AHD-021", 23.05, 72.59), anchor_camera_id: "camera-2", rank: 1, tier: 1, confidence: "high", eta_min_seconds: 240, eta_max_seconds: 420, distance_m: 3100, reasons: ["directionally compatible", "camera operational"], graph_method: "geospatial_directional_fallback", evidence_class: "predicted" }],
  route_segments: [{ source_camera_id: "camera-1", destination_camera_id: "camera-2", coordinates: [[72.57, 23.03], [72.58, 23.04]], segment_class: "inferred", method: "inferred_geodesic_connector", confidence: "high" }],
  activity: [],
  first_seen_at: "2026-08-29T10:01:00Z",
  last_seen_at: "2026-08-29T10:08:00Z",
  last_confirmed_camera: camera("camera-2", "CAM-AHD-014", 23.04, 72.58),
  movement_direction: "north-east",
  coverage_gaps: ["Verified road topology is unavailable."],
  prediction_basis: "Bounded geospatial and directional fallback; no verified road-network claim",
  next_recalculation_seconds: 30,
};

describe("Special Investigation Engine", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("runs the disclosed scenario through the real workspace and separates evidence classes", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/investigations") && method === "GET") return Promise.resolve(json({ items: [], total: 0 }));
      if (url.endsWith("/investigations/demo-scenario")) return Promise.resolve(json({ target_plate: "GJ01AB1234", events_created: 3, cameras_used: 3, disclosure: "Synthetic demonstration observations; never present these records as operational evidence." }));
      if (url.endsWith("/investigations") && method === "POST") return Promise.resolve(json(workspace, 201));
      if (url.endsWith("/investigations/case-1/prediction-backtest")) return Promise.resolve(json({
        case_id: "case-1",
        eligible_transitions: 1,
        evaluated_transitions: 1,
        top_1_accuracy: 1,
        top_3_accuracy: 1,
        top_5_accuracy: 1,
        coverage: 1,
        evaluation_basis: "Retrospective engineering evaluation",
        steps: [],
      }));
      if (url.endsWith("/investigations/case-1")) return Promise.resolve(json(workspace));
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SpecialInvestigationPage />);

    fireEvent.click(await screen.findByRole("button", { name: /load judge demonstration/i }));
    expect(await screen.findByText(/Demonstration data loaded/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /start investigation/i }));

    expect((await screen.findAllByText("INV-2026-A1B2C3")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("GJ01AB1234").length).toBeGreaterThan(0);
    expect(screen.getByText("CAM-AHD-021", { selector: ".sie-candidate-list strong" })).toBeInTheDocument();
    expect(screen.getByText(/Ranked candidates, not guaranteed destinations/i)).toBeInTheDocument();
    expect(screen.getByText("CCTV coverage gap")).toBeInTheDocument();
    expect(await screen.findByText("Prediction replay")).toBeInTheDocument();
    expect(screen.getByText(/not target-presence probability/i)).toBeInTheDocument();
    expect(screen.getByTestId("investigation-map")).toBeInTheDocument();
    expect(screen.getAllByText("Observed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Inferred").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Predicted").length).toBeGreaterThan(0);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/investigations"),
      expect.objectContaining({ headers: expect.any(Object) }),
    ));
  });
});
