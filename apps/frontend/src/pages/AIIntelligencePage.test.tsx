import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AIIntelligencePage } from "./AIIntelligencePage";

const response = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

const overview = {
  available: true,
  total_detections: 1260,
  vehicle_detections: 1044,
  plate_detections: 44,
  readable_plate_detections: 42,
  consensus_plate_detections: 38,
  visual_profiles: 12,
  visual_pending: 0,
  visual_failed: 0,
  unique_tracks: 231,
  source_count: 1,
  frame_count: 223,
  average_confidence: 0.741,
  average_ocr_confidence: 0.87,
  first_observed_at: "2026-08-31 10:00:00",
  last_observed_at: "2026-08-31 10:01:00",
  class_counts: [{ class_name: "car", count: 773, average_confidence: 0.74 }],
  models: [{ model_id: "SVC-OCR-HYBRID-001", key: "plate_ocr", name: "Hybrid plate OCR", purpose: "Plate OCR", status: "configured", detail: "Google primary with Groq fallback", output_count: 42 }],
  features: [{ key: "vehicle_detection", name: "Vehicle detection", status: "observed", description: "Localizes vehicles.", evidence: "1,260 crops" }],
  disclosure: "Observed confidence is not labelled-set accuracy or an enforcement decision.",
};

const detections = {
  items: [{ id: 5, evidence_id: "VEH-00000005", model_id: "MDL-VEH-001", model_name: "yolo26n.pt", source_label: "traffic.mp4", frame: 42, time_ms: 1400, track_id: 7, class_id: 2, class_name: "car", confidence: 0.91, box: [1, 2, 101, 52], width: 100, height: 50, created_at: "2026-08-31 10:00:00", image_url: "/api/v1/ai/detections/5/image" }],
  total: 1, page: 1, page_size: 12, pages: 1,
};

const plates = {
  items: [{ id: 9, evidence_id: "ANPR-00000009", detector_model_id: "MDL-ANPR-001", detector_model_name: "license_plate_detector.pt", ocr_model_id: "SVC-OCR-HYBRID-001", source_detection_id: 5, source_label: "traffic.mp4", frame: 42, time_ms: 1400, track_id: 7, plate_text: "GJ01AB1234", ocr_confidence: 0.94, ocr_raw_text: "GJ 01 AB 1234", ocr_raw_confidence: 0.91, ocr_consensus_count: 2, ocr_candidates: [{ provider: "Google Cloud Vision", status: "completed", raw_text: "GJ 01 AB 1234", normalized_text: "GJ01AB1234", confidence: 0.91, processing_ms: 186, error: null }, { provider: "Groq", status: "completed", raw_text: "GJ01AB1234", normalized_text: "GJ01AB1234", confidence: 0.97, processing_ms: 522, error: null }], ocr_selected_provider: "hybrid", ocr_decision: "providers_agree", ocr_decision_reason: "Google and Groq independently returned the same normalized plate.", ocr_review_required: false, detection_confidence: 0.88, box: [2, 3, 80, 24], width: 78, height: 21, ocr_provider: "hybrid-ocr:hybrid", ocr_status: "COMPLETED", source_vehicle_evidence_id: "VEH-00000005", source_vehicle_image_url: "/api/v1/ai/detections/5/image", created_at: "2026-08-31 10:00:01", image_url: "/api/v1/ai/plates/9/image" }],
  total: 1, page: 1, page_size: 10, pages: 1,
};

describe("AIIntelligencePage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows real vehicle and plate outcomes with their interpretation boundary", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/ai/overview")) return Promise.resolve(response(overview));
      if (url.includes("/ai/detections")) return Promise.resolve(response(detections));
      if (url.includes("/ai/plates")) return Promise.resolve(response(plates));
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AIIntelligencePage />);

    expect((await screen.findAllByText("1,044")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("GJ01AB1234").length).toBeGreaterThan(0);
    expect(screen.getByText("Providers Agree")).toBeInTheDocument();
    expect(screen.getByText("Google Cloud Vision")).toBeInTheDocument();
    expect(screen.getByText("Groq")).toBeInTheDocument();
    expect(screen.getByText("Hybrid plate OCR")).toBeInTheDocument();
    expect(screen.getByText(/not labelled-set accuracy/i)).toBeInTheDocument();
    expect(screen.getByAltText("car detection from traffic.mp4")).toHaveAttribute(
      "src",
      "/api/v1/ai/detections/5/image",
    );

    fireEvent.click(screen.getByRole("button", { name: "Truck" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("class_name=truck"),
      expect.anything(),
    ));
  });
});
