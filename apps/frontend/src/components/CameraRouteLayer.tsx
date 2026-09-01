import { CircleMarker, Polyline, Tooltip } from "react-leaflet";
import { routeLatLngs, type CameraRoutePoint } from "../lib/route";

/**
 * Reusable route overlay for the future cross-camera correlation module.
 * The GIS module owns rendering only; it never invents movement observations.
 */
export function CameraRouteLayer({ points }: { points: CameraRoutePoint[] }) {
  const ordered = [...points]
    .filter((point) => Number.isFinite(point.latitude) && Number.isFinite(point.longitude))
    .sort((left, right) => left.sequence - right.sequence);
  if (ordered.length === 0) return null;

  return (
    <>
      {ordered.length > 1 ? (
        <Polyline
          positions={routeLatLngs(ordered)}
          pathOptions={{ color: "#6ee7df", opacity: 0.88, weight: 4, dashArray: "8 8" }}
        />
      ) : null}
      {ordered.map((point, index) => (
        <CircleMarker
          key={`${point.cameraId}-${point.sequence}`}
          center={[point.latitude, point.longitude]}
          radius={7}
          pathOptions={{ color: "#dffffd", fillColor: "#159f9d", fillOpacity: 1, weight: 2 }}
        >
          <Tooltip direction="top">
            <div className="route-tooltip"><strong>{index + 1}. {point.label ?? point.cameraId}</strong>{point.observedAt ? <small>{point.observedAt}</small> : null}</div>
          </Tooltip>
        </CircleMarker>
      ))}
    </>
  );
}
