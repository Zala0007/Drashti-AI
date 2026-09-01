import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { registryApi } from "../lib/api";
import type { Camera, CameraGeoJson, CameraStatistics } from "../types/registry";
import { GisOperationsPage } from "./GisOperationsPage";

vi.mock("../components/CameraMap", () => ({
  CameraMap: ({ data, selectedId, onSelect }: { data: CameraGeoJson | null; selectedId: string | null; onSelect: (id: string) => void }) => (
    <div data-testid="operational-map">
      <span>{data?.features.length ?? 0} markers</span>
      <span>{selectedId ?? "none selected"}</span>
      <button type="button" onClick={() => onSelect("camera-1")}>Select map marker</button>
    </div>
  ),
}));

const camera: Camera = {
  id: "camera-1",
  camera_code: "CAM-AHD-001",
  camera_name: "Central Junction",
  department_id: "dept-1",
  department: { id: "dept-1", code: "HOME", name: "Home Department" },
  district: "Ahmedabad",
  city: "Ahmedabad",
  location_description: "Central Junction",
  latitude: 23.02,
  longitude: 72.57,
  camera_type: "anpr",
  vendor: "Acme Vision",
  vms: "Open VMS",
  connectivity_type: "fiber",
  stream_protocol: "rtsp",
  rtsp_capable: true,
  onvif_capable: true,
  status: "active",
  health: "online",
  storage_details: {},
  ai_enabled: true,
  ai_capabilities: ["anpr"],
  ownership: "government",
  tags: [],
  created_at: "2026-08-23T10:00:00Z",
  updated_at: "2026-08-23T10:00:00Z",
};

const geoJson: CameraGeoJson = {
  type: "FeatureCollection",
  number_matched: 1,
  number_returned: 1,
  features: [{
    type: "Feature",
    id: "camera-1",
    geometry: { type: "Point", coordinates: [72.57, 23.02] },
    properties: {
      camera_code: camera.camera_code,
      camera_name: camera.camera_name,
      department_id: "dept-1",
      department_name: "Home Department",
      district: camera.district,
      city: camera.city,
      location_description: camera.location_description,
      vendor: camera.vendor,
      vms: camera.vms,
      status: "active",
      health: "online",
      ai_enabled: true,
      ai_capabilities: ["anpr"],
    },
  }],
};

const statistics: CameraStatistics = { total: 1, online: 1, offline: 0, degraded: 0, unknown: 0, ai_enabled: 1 };

function Harness({ onOpen }: { onOpen: (id: string) => void }) {
  const [focused, setFocused] = useState<string | null>(null);
  return <GisOperationsPage departments={[camera.department!]} focusedCameraId={focused} onFocusCamera={setFocused} onOpenCamera={onOpen} />;
}

describe("GIS Operations", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("applies canonical filters, centres search results and opens real details", async () => {
    vi.spyOn(registryApi, "filterOptions").mockResolvedValue({
      districts: ["Ahmedabad"], cities: ["Ahmedabad"], vendors: ["Acme Vision"], vms: ["Open VMS"],
      ai_capabilities: ["anpr"], camera_types: ["anpr"], connectivity_types: ["fiber"], stream_protocols: ["rtsp"],
    });
    const geoSpy = vi.spyOn(registryApi, "geoJson").mockResolvedValue(geoJson);
    vi.spyOn(registryApi, "cameras").mockResolvedValue({ items: [camera], total: 1, page: 1, page_size: 100, pages: 1 });
    vi.spyOn(registryApi, "statistics").mockResolvedValue(statistics);
    const onOpen = vi.fn();
    render(<Harness onOpen={onOpen} />);

    expect(await screen.findByText("Canonical filter options")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("City"), { target: { value: "Ahmedabad" } });
    await waitFor(() => expect(geoSpy).toHaveBeenLastCalledWith(expect.objectContaining({ city: "Ahmedabad" }), expect.any(AbortSignal)));

    fireEvent.change(screen.getByPlaceholderText("Search camera ID, name, location or department"), { target: { value: "CAM-AHD" } });
    const result = await screen.findByRole("button", { name: /Central Junction CAM-AHD-001/ });
    fireEvent.click(result);
    expect(screen.getByTestId("operational-map")).toHaveTextContent("camera-1");
    fireEvent.click(screen.getByRole("button", { name: "Open camera details" }));
    expect(onOpen).toHaveBeenCalledWith("camera-1");
    expect(screen.getByText("Live operations managed separately")).toBeInTheDocument();
  });

  it("derives filter choices when the canonical options endpoint is unavailable", async () => {
    vi.spyOn(registryApi, "filterOptions").mockRejectedValue(new Error("older API"));
    vi.spyOn(registryApi, "geoJson").mockResolvedValue(geoJson);
    vi.spyOn(registryApi, "cameras").mockResolvedValue({ items: [camera], total: 1, page: 1, page_size: 100, pages: 1 });
    vi.spyOn(registryApi, "statistics").mockResolvedValue(statistics);
    render(<Harness onOpen={vi.fn()} />);

    expect(await screen.findByText("Filter values derived from loaded registry data")).toBeInTheDocument();
    expect((await screen.findAllByRole("option", { name: "Ahmedabad" })).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("1 markers")).toBeInTheDocument();
  });

  it("focuses a vehicle-evidence camera passed from Visual Intelligence", async () => {
    vi.spyOn(registryApi, "filterOptions").mockResolvedValue({
      districts: [], cities: [], vendors: [], vms: [], ai_capabilities: [],
      camera_types: [], connectivity_types: [], stream_protocols: [],
    });
    vi.spyOn(registryApi, "geoJson").mockResolvedValue(geoJson);
    vi.spyOn(registryApi, "cameras").mockResolvedValue({ items: [camera], total: 1, page: 1, page_size: 100, pages: 1 });
    vi.spyOn(registryApi, "statistics").mockResolvedValue(statistics);
    sessionStorage.setItem("drishti-visual-camera", "camera-1");

    render(<Harness onOpen={vi.fn()} />);

    await waitFor(() => expect(screen.getByTestId("operational-map")).toHaveTextContent("camera-1"));
    expect(sessionStorage.getItem("drishti-visual-camera")).toBeNull();
  });
});
