import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  Crosshair,
  Info,
  Layers3,
  MapPinned,
  RefreshCw,
  Route,
  Search,
  ServerCog,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CameraFilters } from "../components/CameraFilters";
import { CameraMap } from "../components/CameraMap";
import { StatusBadge } from "../components/StatusBadge";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { ApiError, registryApi } from "../lib/api";
import { cameraHealth, cameraId, departmentLabel, formatTimestamp, titleCase } from "../lib/format";
import { deriveFilterOptions, emptyCameraFilters, mergeFilterOptions } from "../lib/registryView";
import type {
  Camera as CameraRecord,
  CameraFilterOptions,
  CameraFilters as Filters,
  CameraGeoJson,
  CameraStatistics,
  Department,
  Page,
} from "../types/registry";

interface GisOperationsPageProps {
  departments: Department[];
  focusedCameraId: string | null;
  onFocusCamera: (id: string) => void;
  onOpenCamera: (id: string) => void;
}

const messageFor = (error: unknown): string =>
  error instanceof ApiError ? error.message : "GIS data could not be loaded. Please retry.";

export function GisOperationsPage({ departments, focusedCameraId, onFocusCamera, onOpenCamera }: GisOperationsPageProps) {
  const [filters, setFilters] = useState<Filters>(emptyCameraFilters);
  const debouncedFilters = useDebouncedValue(filters, 280);
  const [geoJson, setGeoJson] = useState<CameraGeoJson | null>(null);
  const [cameraPage, setCameraPage] = useState<Page<CameraRecord> | null>(null);
  const [statistics, setStatistics] = useState<CameraStatistics | null>(null);
  const [canonicalOptions, setCanonicalOptions] = useState<CameraFilterOptions | null>(null);
  const [optionsSource, setOptionsSource] = useState<"loading" | "canonical" | "fallback">("loading");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);

  useEffect(() => {
    const linkedCamera = sessionStorage.getItem("drishti-visual-camera");
    if (!linkedCamera) return;
    sessionStorage.removeItem("drishti-visual-camera");
    onFocusCamera(linkedCamera);
  }, [onFocusCamera]);

  useEffect(() => {
    const controller = new AbortController();
    setOptionsSource("loading");
    registryApi.filterOptions(controller.signal)
      .then((options) => {
        setCanonicalOptions(options);
        setOptionsSource("canonical");
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === "AbortError") return;
        setCanonicalOptions(null);
        setOptionsSource("fallback");
      });
    return () => controller.abort();
  }, [refreshKey]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      registryApi.geoJson(debouncedFilters, controller.signal),
      registryApi.cameras(debouncedFilters, 1, 100, controller.signal),
      registryApi.statistics(debouncedFilters, controller.signal),
    ])
      .then(([features, cameras, stats]) => {
        setGeoJson(features);
        setCameraPage(cameras);
        setStatistics(stats);
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === "AbortError") return;
        setError(messageFor(requestError));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [debouncedFilters, refreshKey]);

  const options = useMemo(() => mergeFilterOptions(
    canonicalOptions,
    deriveFilterOptions(geoJson, cameraPage?.items ?? []),
  ), [cameraPage, canonicalOptions, geoJson]);
  const selectedFeature = useMemo(
    () => (geoJson?.features ?? []).find((feature) => (feature.id ?? feature.properties.camera_uuid ?? feature.properties.id ?? feature.properties.camera_code) === focusedCameraId),
    [focusedCameraId, geoJson],
  );
  const activeFilterCount = Object.values(filters).filter(Boolean).length;
  const total = statistics?.total ?? cameraPage?.total ?? geoJson?.number_matched ?? 0;

  return (
    <div className="page gis-page">
      <header className="page-header gis-page__header">
        <div>
          <div className="page-header__context"><span>GIS foundation</span><i />Operational camera layer</div>
          <h1>GIS Operations</h1>
          <p>Search, filter and inspect authoritative camera locations across Gujarat.</p>
        </div>
        <div className="page-header__actions">
          <span className="map-scale-note"><Layers3 size={15} /><span><strong>Clustered rendering</strong><small>Designed for viewport-scale expansion</small></span></span>
          <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}><RefreshCw className={loading ? "spin" : undefined} size={16} /> Refresh map</button>
        </div>
      </header>

      <section className="gis-filter-shell">
        <div className="gis-filter-shell__heading">
          <span><Crosshair aria-hidden="true" size={17} /><strong>Camera discovery</strong><small>{activeFilterCount ? `${activeFilterCount} active filter${activeFilterCount === 1 ? "" : "s"}` : "Unfiltered statewide view"}</small></span>
          {optionsSource === "fallback" ? <span className="filter-source-note"><Info size={13} /> Filter values derived from loaded registry data</span> : null}
          {optionsSource === "canonical" ? <span className="filter-source-note filter-source-note--live"><CheckCircle2 size={13} /> Canonical filter options</span> : null}
          {optionsSource === "loading" ? <span className="filter-source-note"><RefreshCw className="spin" size={13} /> Loading filter options</span> : null}
        </div>
        <CameraFilters value={filters} departments={departments} onChange={setFilters} resultCount={total} options={options} advanced />
      </section>

      {filters.search && cameraPage?.items.length ? (
        <section className="gis-search-results" aria-label="Camera search results">
          <span><Search size={14} /> Select a result to centre and inspect</span>
          <div>
            {cameraPage.items.slice(0, 6).map((camera) => (
              <button type="button" key={cameraId(camera)} onClick={() => onFocusCamera(cameraId(camera))}>
                <Camera size={15} /><span><strong>{camera.camera_name}</strong><small>{camera.camera_code} · {camera.city || camera.district} · {departmentLabel(camera)}</small></span><StatusBadge value={cameraHealth(camera)} />
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {error ? <div className="gis-inline-error" role="alert"><AlertTriangle size={16} /><span><strong>GIS results could not be refreshed</strong><small>{error}</small></span><button type="button" onClick={refresh}>Retry</button></div> : null}

      <section className="gis-operations-layout">
        <article className="gis-map-panel">
          <CameraMap
            data={geoJson}
            loading={loading}
            error={error}
            selectedId={focusedCameraId}
            onSelect={onFocusCamera}
            onRetry={refresh}
            mode="operations"
          />
        </article>

        <aside className="gis-rail">
          <section className="gis-rail__summary">
            <header><span className="panel-kicker">Filtered network posture</span><h2>{total.toLocaleString("en-IN")} cameras</h2></header>
            <div className="health-matrix">
              <HealthMetric label="Online" value={statistics?.online} status="online" glyph="✓" />
              <HealthMetric label="Offline" value={statistics?.offline} status="offline" glyph="×" />
              <HealthMetric label="Degraded" value={statistics?.degraded} status="degraded" glyph="!" />
              <HealthMetric label="Unknown" value={statistics?.unknown} status="unknown" glyph="?" />
            </div>
          </section>

          <section className="gis-selected-card">
            <header><span className="panel-kicker">Map selection</span><h2>Selected asset</h2></header>
            {selectedFeature ? (
              <div>
                <span className={`selected-camera-glyph selected-camera-glyph--${selectedFeature.properties.health ?? "unknown"}`}><Camera size={20} /></span>
                <div className="selected-camera-title"><strong>{selectedFeature.properties.camera_name}</strong><code>{selectedFeature.properties.camera_code}</code></div>
                <dl>
                  <div><dt>Department</dt><dd>{selectedFeature.properties.department_name ?? "Unavailable"}</dd></div>
                  <div><dt>Location</dt><dd>{selectedFeature.properties.location_description || selectedFeature.properties.city || selectedFeature.properties.district || "Unavailable"}</dd></div>
                  <div><dt>Vendor / VMS</dt><dd>{[selectedFeature.properties.vendor, selectedFeature.properties.vms].filter(Boolean).join(" / ") || "Not recorded"}</dd></div>
                  <div><dt>Lifecycle</dt><dd>{titleCase(selectedFeature.properties.status ?? "unknown")}</dd></div>
                  <div><dt>Operational health</dt><dd>{titleCase(selectedFeature.properties.health ?? "unknown")}</dd></div>
                  <div><dt>Last heartbeat</dt><dd>{formatTimestamp(selectedFeature.properties.last_heartbeat)}</dd></div>
                  <div><dt>AI capabilities</dt><dd>{selectedFeature.properties.ai_capabilities?.length ? selectedFeature.properties.ai_capabilities.map(titleCase).join(", ") : "None recorded"}</dd></div>
                </dl>
                <button type="button" className="button button--secondary selected-details-action" onClick={() => onOpenCamera(focusedCameraId!)}>Open camera details</button>
                <p className="live-unavailable"><ServerCog size={14} /><span><strong>Live operations managed separately</strong><small>Open Live Operations to start or inspect this camera stream.</small></span></p>
              </div>
            ) : (
              <div className="selection-empty"><MapPinned size={25} /><strong>No camera selected</strong><p>Select a marker or search result to open its registry profile.</p></div>
            )}
          </section>

          <section className="route-readiness-card">
            <Route aria-hidden="true" size={20} />
            <span><strong>Route overlay ready</strong><small>The reusable polyline layer is prepared for verified cross-camera vehicle observations. No route is fabricated at this stage.</small></span>
          </section>

          <section className="alert-readiness-card">
            <AlertTriangle aria-hidden="true" size={18} />
            <span><strong>Alert visualization reserved</strong><small>Watchlist markers activate only after authoritative alert events exist.</small></span>
          </section>
        </aside>
      </section>
    </div>
  );
}

function HealthMetric({ label, value, status, glyph }: { label: string; value?: number; status: string; glyph: string }) {
  return <div className={`health-metric health-metric--${status}`}><i>{glyph}</i><span><strong>{typeof value === "number" ? value.toLocaleString("en-IN") : "—"}</strong><small>{label}</small></span></div>;
}
