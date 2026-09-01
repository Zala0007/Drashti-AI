import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { CameraRouteLayer } from "./CameraRouteLayer";

vi.mock("react-leaflet", () => ({
  Polyline: ({ positions }: { positions: Array<[number, number]> }) => <div data-testid="route-polyline">{JSON.stringify(positions)}</div>,
  CircleMarker: ({ children }: { children: ReactNode }) => <div data-testid="route-point">{children}</div>,
  Tooltip: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

describe("CameraRouteLayer", () => {
  it("renders an ordered polyline and evidence camera points", () => {
    render(<CameraRouteLayer points={[
      { cameraId: "CAM-14", latitude: 23.03, longitude: 72.58, sequence: 2, label: "Camera 14" },
      { cameraId: "CAM-07", latitude: 23.02, longitude: 72.57, sequence: 1, label: "Camera 07" },
    ]} />);

    expect(screen.getByTestId("route-polyline")).toHaveTextContent("[[23.02,72.57],[23.03,72.58]]");
    expect(screen.getAllByTestId("route-point")).toHaveLength(2);
    expect(screen.getByText("1. Camera 07")).toBeInTheDocument();
  });
});
