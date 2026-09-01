import { useEffect, useMemo } from "react";
import L, { type LatLngExpression } from "leaflet";
import { MapContainer, Marker, TileLayer, Tooltip, useMap } from "react-leaflet";
import { Crosshair, Layers3, MapPinned } from "lucide-react";
import { titleCase } from "../lib/format";
import { geoFeatureHealth, geoFeatureId } from "../lib/registryView";
import type { CameraGeoFeature, CameraGeoJson, HealthStatus } from "../types/registry";
import type { CameraRoutePoint } from "../lib/route";
import { CameraRouteLayer } from "./CameraRouteLayer";
import { ErrorState, LoadingState } from "./Feedback";
import { MarkerClusterLayer } from "./MarkerClusterLayer";
import { StatusBadge } from "./StatusBadge";

interface CameraMapProps {
  data: CameraGeoJson | null;
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRetry: () => void;
  mode?: "embedded" | "operations" | "overview";
  routePoints?: CameraRoutePoint[];
}

const GUJARAT_CENTER: LatLngExpression = [22.72, 71.64];
const tileUrl = import.meta.env.VITE_MAP_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const tileAttribution = import.meta.env.VITE_MAP_ATTRIBUTION || "&copy; OpenStreetMap contributors";

const healthGlyph: Record<HealthStatus, string> = { online: "✓", offline: "×", degraded: "!", unknown: "?" };

const markerIcon = (health: HealthStatus, selected: boolean): L.DivIcon => L.divIcon({
  className: "camera-marker-host",
  html: `<span class="camera-marker camera-marker--${health}${selected ? " camera-marker--selected" : ""}"><b>${healthGlyph[health]}</b></span>`,
  iconSize: selected ? [30, 30] : [24, 24],
  iconAnchor: selected ? [15, 15] : [12, 12],
});

function FitCameraBounds({ features }: { features: CameraGeoFeature[] }) {
  const map = useMap();
  const boundsSignature = features
    .map((feature) => {
      const [longitude, latitude] = feature.geometry.coordinates;
      return `${geoFeatureId(feature)}@${longitude},${latitude}`;
    })
    .join("|");
  useEffect(() => {
    const coordinates = features
      .map((feature) => [feature.geometry.coordinates[1], feature.geometry.coordinates[0]] as [number, number])
      .filter(([latitude, longitude]) => Number.isFinite(latitude) && Number.isFinite(longitude));
    if (coordinates.length === 1) map.setView(coordinates[0], 14, { animate: true });
    if (coordinates.length > 1) map.fitBounds(coordinates, { padding: [38, 38], maxZoom: 14, animate: true });
  }, [boundsSignature, features, map]);
  return null;
}

function FocusCamera({ feature }: { feature?: CameraGeoFeature }) {
  const map = useMap();
  const id = feature ? geoFeatureId(feature) : null;
  useEffect(() => {
    if (!feature) return;
    const [longitude, latitude] = feature.geometry.coordinates;
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
    map.flyTo([latitude, longitude], Math.max(map.getZoom(), 15), { animate: true, duration: 0.55 });
  }, [feature, id, map]);
  return null;
}

export function CameraMap({
  data,
  loading,
  error,
  selectedId,
  onSelect,
  onRetry,
  mode = "embedded",
  routePoints = [],
}: CameraMapProps) {
  const validFeatures = useMemo(
    () => (data?.features ?? []).filter((feature) => {
      const [longitude, latitude] = feature.geometry.coordinates;
      return Number.isFinite(latitude) && Number.isFinite(longitude);
    }),
    [data],
  );

  return (
    <div className={`map-shell map-shell--${mode}`}>
      <div className="map-toolbar">
        <span><Layers3 aria-hidden="true" size={15} /> Operational GIS</span>
        <span className="map-toolbar__count"><Crosshair aria-hidden="true" size={14} /> {validFeatures.length.toLocaleString("en-IN")} mapped</span>
      </div>
      <MapContainer center={GUJARAT_CENTER} zoom={7} minZoom={5} maxZoom={19} zoomControl attributionControl>
        <TileLayer attribution={tileAttribution} url={tileUrl} maxZoom={19} />
        <MarkerClusterLayer
          chunkedLoading
          showCoverageOnHover={false}
          spiderfyOnMaxZoom
          maxClusterRadius={48}
          iconCreateFunction={(cluster) => L.divIcon({
            html: `<span class="camera-cluster"><b>${cluster.getChildCount()}</b><i></i></span>`,
            className: "camera-cluster-host",
            iconSize: [42, 42],
          })}
        >
          {validFeatures.map((feature) => {
            const id = geoFeatureId(feature);
            const [longitude, latitude] = feature.geometry.coordinates;
            const health = geoFeatureHealth(feature);
            return (
              <Marker
                key={id}
                position={[latitude, longitude]}
                icon={markerIcon(health, selectedId === id)}
                eventHandlers={{ click: () => onSelect(id) }}
              >
                <Tooltip direction="top" offset={[0, -12]} opacity={1}>
                  <div className="map-tooltip">
                    <div><strong>{feature.properties.camera_name}</strong><span>{feature.properties.camera_code}</span></div>
                    <p>{feature.properties.location_description || feature.properties.city || feature.properties.district || "Location unavailable"}</p>
                    <StatusBadge value={health} />
                    <small>{feature.properties.department_name || "Department unavailable"}</small>
                    {feature.properties.ai_enabled ? <small>{feature.properties.ai_capabilities?.length ? feature.properties.ai_capabilities.map(titleCase).join(" · ") : "AI analytics enabled"}</small> : null}
                    <small>Select marker for full asset details</small>
                  </div>
                </Tooltip>
              </Marker>
            );
          })}
        </MarkerClusterLayer>
        <CameraRouteLayer points={routePoints} />
        {validFeatures.length ? <FitCameraBounds features={validFeatures} /> : null}
        <FocusCamera feature={validFeatures.find((feature) => geoFeatureId(feature) === selectedId)} />
      </MapContainer>

      <div className="map-legend" aria-label="Camera health legend">
        {(["online", "degraded", "offline", "unknown"] as const).map((status) => (
          <span key={status}><i className={`legend-dot legend-dot--${status}`}>{healthGlyph[status]}</i>{titleCase(status)}</span>
        ))}
      </div>

      {loading && !data ? <div className="map-overlay"><LoadingState label="Loading GIS layer…" /></div> : null}
      {error && !data ? <div className="map-overlay"><ErrorState message={error} onRetry={onRetry} /></div> : null}
      {!loading && !error && data && validFeatures.length === 0 ? (
        <div className="map-overlay map-overlay--empty">
          <MapPinned aria-hidden="true" size={28} />
          <strong>No mapped cameras</strong>
          <p>No coordinates match the current filters.</p>
        </div>
      ) : null}
    </div>
  );
}
