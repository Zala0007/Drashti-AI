import L from "leaflet";
import { MapPinned, RotateCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { TileLayer } from "react-leaflet";
import { mapTileConfig, type MapTheme } from "../lib/mapTiles";

// Do not use Leaflet's internal empty GIF: it suppresses the tileerror event.
const EMPTY_TILE = "data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22256%22 height=%22256%22/%3E";
const readTheme = (): MapTheme => document.documentElement.dataset.theme === "dark" ? "dark" : "light";

/** Shared by every GIS surface so tile policy, attribution and theme stay consistent. */
export function MapBasemap() {
  const [theme, setTheme] = useState<MapTheme>(readTheme);
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(readTheme()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  const config = mapTileConfig(theme);
  return <BasemapTiles key={config.url} {...config} />;
}

function BasemapTiles({ url, attribution, className }: ReturnType<typeof mapTileConfig>) {
  const layer = useRef<L.TileLayer>(null);
  const failedTiles = useRef(new Set<HTMLElement>());
  const [unavailable, setUnavailable] = useState(false);
  const eventHandlers = useMemo(() => ({
    tileerror: ({ tile }: { tile: HTMLElement }) => {
      failedTiles.current.add(tile);
      setUnavailable(true);
    },
    tileunload: ({ tile }: { tile: HTMLElement }) => {
      failedTiles.current.delete(tile);
      setUnavailable(failedTiles.current.size > 0);
    },
  }), []);

  const retry = () => {
    failedTiles.current.clear();
    setUnavailable(false);
    // A deliberate retry respects the provider cache and avoids automatic request loops.
    layer.current?.redraw();
  };

  return <>
    <TileLayer
      ref={layer}
      attribution={attribution}
      url={url}
      className={className}
      maxZoom={19}
      maxNativeZoom={19}
      referrerPolicy="strict-origin-when-cross-origin"
      errorTileUrl={EMPTY_TILE}
      updateWhenIdle
      updateWhenZooming={false}
      keepBuffer={1}
      eventHandlers={eventHandlers}
    />
    {unavailable ? <div className="map-basemap-status" role="status" ref={(element) => {
      if (element) {
        L.DomEvent.disableClickPropagation(element);
        L.DomEvent.disableScrollPropagation(element);
      }
    }}>
      <MapPinned size={17} aria-hidden="true" />
      <span><strong>Map background unavailable</strong><small>Camera locations and routes remain available.</small></span>
      <button type="button" onClick={retry}><RotateCw size={14} aria-hidden="true" />Retry map</button>
    </div> : null}
  </>;
}
