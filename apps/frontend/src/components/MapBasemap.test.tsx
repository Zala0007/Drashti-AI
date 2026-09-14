import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import L from "leaflet";
import { MapContainer, Marker } from "react-leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MapBasemap } from "./MapBasemap";

const renderMap = () => render(<MapContainer center={[23, 72]} zoom={7}>
  <MapBasemap />
  <Marker position={[23, 72]} icon={L.divIcon({ html: "Camera A" })} />
</MapContainer>);

const tiles = () => Array.from(document.querySelectorAll<HTMLImageElement>("img.leaflet-tile"));

beforeEach(() => {
  document.documentElement.dataset.theme = "light";
  for (const name of ["VITE_MAP_TILE_URL", "VITE_MAP_LIGHT_TILE_URL", "VITE_MAP_DARK_TILE_URL", "VITE_MAP_ATTRIBUTION"]) {
    vi.stubEnv(name, "");
  }
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  delete document.documentElement.dataset.theme;
});

describe("MapBasemap", () => {
  it("creates canonical OSM tile images with an identifying referrer and visible attribution", () => {
    // Existing deployments may still provide the legacy subdomain URL.
    vi.stubEnv("VITE_MAP_TILE_URL", "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png");
    renderMap();

    expect(tiles().length).toBeGreaterThan(0);
    for (const tile of tiles()) {
      expect(tile.src).toMatch(/^https:\/\/tile\.openstreetmap\.org\//);
      expect(tile.referrerPolicy).toBe("strict-origin-when-cross-origin");
    }
    expect(screen.getByRole("link", { name: "OpenStreetMap" })).toHaveAttribute("href", "https://www.openstreetmap.org/copyright");
  });

  it("keeps camera markers usable when a tile fails and allows a deliberate retry", () => {
    renderMap();
    const failedTile = tiles()[0];
    fireEvent.error(failedTile);

    expect(screen.getByRole("status")).toHaveTextContent("Map background unavailable");
    expect(screen.getByText("Camera A")).toBeInTheDocument();
    expect(failedTile.src).toMatch(/^data:image\/svg\+xml/);

    fireEvent.click(screen.getByRole("button", { name: "Retry map" }));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(tiles()).not.toContain(failedTile);
    expect(tiles().every((tile) => tile.src.startsWith("https://tile.openstreetmap.org/"))).toBe(true);
    expect(screen.getByText("Camera A")).toBeInTheDocument();
  });

  it("changes native provider styles with the document theme without recreating camera markers", async () => {
    vi.stubEnv("VITE_MAP_LIGHT_TILE_URL", "https://maps.example.org/light/{z}/{x}/{y}.png");
    vi.stubEnv("VITE_MAP_DARK_TILE_URL", "https://maps.example.org/dark/{z}/{x}/{y}.png");
    vi.stubEnv("VITE_MAP_ATTRIBUTION", "Example mapping service");
    renderMap();
    const marker = screen.getByText("Camera A");
    expect(tiles()[0].src).toContain("/light/");
    expect(document.querySelector(".drashti-basemap--native")).toBeInTheDocument();

    document.documentElement.dataset.theme = "dark";

    await waitFor(() => expect(tiles()[0].src).toContain("/dark/"));
    expect(screen.getByText("Camera A")).toBe(marker);
    expect(screen.getByText(/Example mapping service/)).toBeInTheDocument();
  });
});
