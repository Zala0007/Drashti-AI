import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, registryApi } from "../lib/api";
import type { Camera } from "../types/registry";
import { CameraDetailDrawer } from "./CameraDetailDrawer";

const camera = (id: string, name: string, code: string): Camera => ({
  id,
  camera_code: code,
  camera_name: name,
  department_id: "bd407055-4a9a-47eb-a3b3-3bfc3914563a",
  department: { id: "bd407055-4a9a-47eb-a3b3-3bfc3914563a", code: "HOME", name: "Home Department" },
  district: "Ahmedabad",
  city: "Ahmedabad",
  location_description: "Test junction",
  latitude: 23.0225,
  longitude: 72.5714,
  camera_type: "fixed",
  vendor: "Test vendor",
  model: "T-1",
  vms: "Test VMS",
  connectivity_type: "fiber",
  stream_protocol: "rtsp",
  rtsp_capable: true,
  onvif_capable: true,
  status: "active",
  health: "online",
  last_heartbeat: "2026-08-23T12:00:00Z",
  storage_details: {},
  ai_enabled: false,
  ai_capabilities: [],
  ownership: "government",
  owner_name: "Control room",
  tags: [],
  created_at: "2026-08-23T10:00:00Z",
  updated_at: "2026-08-23T12:00:00Z",
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("CameraDetailDrawer request identity", () => {
  afterEach(() => vi.restoreAllMocks());

  it("hides a prior camera immediately and shows the next request error", async () => {
    const secondRequest = deferred<Camera>();
    vi.spyOn(registryApi, "camera").mockImplementation((id) => {
      if (id === "camera-a") return Promise.resolve(camera("camera-a", "Camera Alpha", "GJ-A-01"));
      return secondRequest.promise;
    });
    vi.spyOn(registryApi, "audit").mockResolvedValue([]);

    const view = render(<CameraDetailDrawer cameraId="camera-a" onClose={vi.fn()} />);
    expect(await screen.findByText("Camera Alpha")).toBeInTheDocument();

    view.rerender(<CameraDetailDrawer cameraId="camera-b" onClose={vi.fn()} />);
    expect(screen.queryByText("Camera Alpha")).not.toBeInTheDocument();
    expect(screen.getByText(/Retrieving camera profile/)).toBeInTheDocument();

    await act(async () => {
      secondRequest.reject(new ApiError("Camera Bravo is unavailable", 503));
      await Promise.resolve();
    });

    expect(await screen.findByText("Camera Bravo is unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Camera Alpha")).not.toBeInTheDocument();
  });
});
