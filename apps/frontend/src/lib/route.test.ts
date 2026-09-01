import { describe, expect, it } from "vitest";
import { routeLatLngs, type CameraRoutePoint } from "./route";

describe("route layer contract", () => {
  it("orders valid camera observations without mutating the event sequence", () => {
    const points: CameraRoutePoint[] = [
      { cameraId: "CAM-21", latitude: 23.02, longitude: 72.57, sequence: 2 },
      { cameraId: "CAM-07", latitude: 22.30, longitude: 70.80, sequence: 1 },
      { cameraId: "INVALID", latitude: Number.NaN, longitude: 70, sequence: 3 },
    ];
    expect(routeLatLngs(points)).toEqual([[22.30, 70.80], [23.02, 72.57]]);
    expect(points[0].cameraId).toBe("CAM-21");
  });
});
