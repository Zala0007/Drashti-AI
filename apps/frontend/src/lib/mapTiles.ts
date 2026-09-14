export type MapTheme = "light" | "dark";

const OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';

export function mapTileConfig(theme: MapTheme, environment: Pick<ImportMetaEnv,
  "VITE_MAP_TILE_URL" | "VITE_MAP_LIGHT_TILE_URL" | "VITE_MAP_DARK_TILE_URL" | "VITE_MAP_ATTRIBUTION"
> = import.meta.env) {
  const themedUrl = theme === "dark" ? environment.VITE_MAP_DARK_TILE_URL : environment.VITE_MAP_LIGHT_TILE_URL;
  const configuredUrl = themedUrl?.trim() || environment.VITE_MAP_TILE_URL?.trim();
  // OSM now documents a single canonical HTTPS endpoint. Normalize older deployments.
  const url = (configuredUrl || OSM_TILE_URL).replace(
    /^https?:\/\/(?:(?:\{s\}|[abc])\.)?tile\.openstreetmap\.org\//,
    "https://tile.openstreetmap.org/",
  );
  const standard = url.startsWith("https://tile.openstreetmap.org/");
  return {
    url,
    attribution: environment.VITE_MAP_ATTRIBUTION?.trim() || OSM_ATTRIBUTION,
    className: standard ? "drashti-basemap--standard" : "drashti-basemap--native",
  };
}
