import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VehicleReIDPanel } from "./VehicleReIDPanel";

const camera = {
  id: "camera-1",
  camera_code: "CAM-AHD-001",
  camera_name: "Ahmedabad Corridor",
  district: "Ahmedabad",
  latitude: 23.03,
  longitude: 72.57,
  health: "online",
  status: "active",
};

const target = {
  id: "observation-target",
  source_observation_id: "source-target",
  camera,
  observed_at: "2026-08-30T10:00:00Z",
  track_id: "TRACK-041",
  plate_text: "GJ01AB1234",
  vehicle_class: "car",
  colour: "white",
  quality_score: .92,
  quality_flags: [],
  crop_available: true,
  embedding_available: true,
  source: "analytics",
};

const match = {
  id: "match-1",
  investigation_id: "investigation-1",
  target,
  candidate: {
    ...target,
    id: "observation-candidate",
    source_observation_id: "source-candidate",
    plate_text: null,
    track_id: "TRACK-102",
    camera: { ...camera, id: "camera-2", camera_code: "CAM-AHD-002" },
    quality_flags: ["plate_unreadable"],
  },
  visual_similarity: .94,
  plate_similarity: null,
  colour_similarity: 1,
  class_similarity: 1,
  temporal_feasibility: 1,
  route_feasibility: 1,
  direction_consistency: 1,
  technical_score: .91,
  assessment: "high",
  status: "probable",
  reasons: ["elapsed time is compatible", "visual embedding similarity 0.94"],
};

afterEach(() => vi.restoreAllMocks());

describe("VehicleReIDPanel", () => {
  it("shows an explainable comparison and requires manual confirmation", async () => {
    const onConfirmed = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = init?.method === "POST" && String(_input).includes("/review")
        ? { ...match, status: "confirmed", reviewed_by: "demo-investigator", reviewed_at: "2026-08-30T10:45:00Z" }
        : {
            investigation_id: "investigation-1",
            target_observation_id: target.id,
            items: [match],
            compared_observations: 1,
            elapsed_ms: 4.2,
            disclosure: "Technical multi-signal ranking; investigator review required.",
          };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }));

    render(<VehicleReIDPanel investigationId="investigation-1" onConfirmed={onConfirmed} />);
    expect(await screen.findByText("CAM-AHD-002")).toBeInTheDocument();
    expect(screen.getByText("PLATE UNREADABLE")).toBeInTheDocument();
    expect(screen.getByText("94%")).toBeInTheDocument();
    expect(screen.getByText(/Machine ranks/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Confirm match/i }));
    await waitFor(() => expect(onConfirmed).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Reviewed by demo-investigator/)).toBeInTheDocument();
  });
});
