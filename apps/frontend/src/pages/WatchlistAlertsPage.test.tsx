import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WatchlistAlertsPage } from "./WatchlistAlertsPage";

const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

const entry = {
  id: "entry-1",
  plate_text: "GJ 01 AB 1234",
  normalized_plate: "GJ01AB1234",
  subject_label: "Evaluation target vehicle",
  reason: "Technical evaluation live watch",
  severity: "critical",
  status: "active",
  valid_from: "2026-09-01T12:00:00Z",
  valid_until: null,
  created_by: "control-room-1",
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
};

const alert = {
  id: "alert-00000001",
  status: "new",
  match_score: 1,
  matched_plate: "GJ01AB1234",
  observed_at: "2026-09-01T12:03:04Z",
  acknowledged_by: null,
  acknowledged_at: null,
  created_at: "2026-09-01T12:03:04Z",
  entry,
  anpr_event_id: "event-1",
  camera_id: "camera-1",
  camera_code: "CAM-EVAL-04",
  camera_name: "Ashram Road Junction",
  district: "Ahmedabad",
  evidence_reference: "/api/v1/ai/plates/9/image",
  ocr_confidence: 0.94,
};

describe("WatchlistAlertsPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders durable watchlist data and acknowledges a live alert", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/watchlist/dashboard")) {
        return Promise.resolve(jsonResponse({
          active_entries: 1,
          total_entries: 1,
          new_alerts: init?.method === "POST" ? 0 : 1,
          latest_alert_at: alert.observed_at,
        }));
      }
      if (url.includes("/watchlist/entries")) {
        return Promise.resolve(jsonResponse({ items: [entry], total: 1 }));
      }
      if (url.includes("/watchlist/alerts/") && init?.method === "POST") {
        return Promise.resolve(jsonResponse({
          ...alert,
          status: "acknowledged",
          acknowledged_by: "demo-operations",
        }));
      }
      if (url.includes("/watchlist/alerts")) {
        return Promise.resolve(jsonResponse({ items: [alert], total: 1, unacknowledged: 1 }));
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<WatchlistAlertsPage />);

    expect((await screen.findAllByText("GJ01AB1234")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("CAM-EVAL-04").length).toBeGreaterThan(0);
    expect(screen.getByAltText("Hybrid OCR evidence for GJ01AB1234")).toHaveAttribute(
      "src",
      "/api/v1/ai/plates/9/image",
    );

    fireEvent.click(screen.getByRole("button", { name: /acknowledge alert/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/watchlist/alerts/alert-00000001/review"),
      expect.objectContaining({ method: "POST" }),
    ));
  });
});
