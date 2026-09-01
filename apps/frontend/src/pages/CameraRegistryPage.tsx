import { Building2, FileUp, Plus, RefreshCw, Satellite, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CameraDetailDrawer } from "../components/CameraDetailDrawer";
import { AddDepartmentModal } from "../components/AddDepartmentModal";
import { CameraFilters } from "../components/CameraFilters";
import { CameraMap } from "../components/CameraMap";
import { CameraTable } from "../components/CameraTable";
import { CsvImportModal } from "../components/CsvImportModal";
import { OnboardCameraModal } from "../components/OnboardCameraModal";
import { SummaryCards } from "../components/SummaryCards";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { ApiError, registryApi } from "../lib/api";
import { cameraId } from "../lib/format";
import { emptyCameraFilters } from "../lib/registryView";
import type { Camera, CameraFilters as Filters, CameraGeoJson, CameraStatistics, Department, Page } from "../types/registry";

interface CameraRegistryPageProps {
  departments: Department[];
  selectedCameraId: string | null;
  onSelectCamera: (id: string | null) => void;
  onRegistryChanged: () => void;
  onDepartmentCreated: (department: Department) => void;
}

const PAGE_SIZE = 20;
const messageFor = (error: unknown): string => error instanceof ApiError ? error.message : "An unexpected registry error occurred.";

export function CameraRegistryPage({ departments, selectedCameraId, onSelectCamera, onRegistryChanged, onDepartmentCreated }: CameraRegistryPageProps) {
  const [filters, setFilters] = useState<Filters>(emptyCameraFilters);
  const debouncedFilters = useDebouncedValue(filters, 300);
  const [page, setPage] = useState(1);
  const [cameraPage, setCameraPage] = useState<Page<Camera> | null>(null);
  const [statistics, setStatistics] = useState<CameraStatistics | null>(null);
  const [geoJson, setGeoJson] = useState<CameraGeoJson | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [mapLoading, setMapLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [onboardOpen, setOnboardOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [departmentOpen, setDepartmentOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null);
  const refresh = useCallback(() => setRefreshKey((key) => key + 1), []);

  useEffect(() => setPage(1), [debouncedFilters]);

  useEffect(() => {
    const controller = new AbortController();
    setListLoading(true);
    setListError(null);
    registryApi.cameras(debouncedFilters, page, PAGE_SIZE, controller.signal)
      .then((data) => {
        setCameraPage(data);
        setLastSyncedAt(new Date());
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setListError(messageFor(error));
      })
      .finally(() => { if (!controller.signal.aborted) setListLoading(false); });
    return () => controller.abort();
  }, [debouncedFilters, page, refreshKey]);

  useEffect(() => {
    const controller = new AbortController();
    setMapLoading(true);
    setMapError(null);
    registryApi.geoJson(debouncedFilters, controller.signal)
      .then(setGeoJson)
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setMapError(messageFor(error));
      })
      .finally(() => { if (!controller.signal.aborted) setMapLoading(false); });
    return () => controller.abort();
  }, [debouncedFilters, refreshKey]);

  useEffect(() => {
    const controller = new AbortController();
    setStatsLoading(true);
    registryApi.statistics(debouncedFilters, controller.signal)
      .then(setStatistics)
      .catch(() => undefined)
      .finally(() => { if (!controller.signal.aborted) setStatsLoading(false); });
    return () => controller.abort();
  }, [debouncedFilters, refreshKey]);

  useEffect(() => {
    if (!notice) return;
    const timeout = window.setTimeout(() => setNotice(null), 4500);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  const lastSynchronized = useMemo(() => lastSyncedAt ? new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(lastSyncedAt) : "Not synchronized", [lastSyncedAt]);

  const refreshAll = () => {
    refresh();
    onRegistryChanged();
  };

  return (
    <div className="page registry-page">
      <header className="page-header">
        <div>
          <div className="page-header__context"><span>Model 1 foundation</span><i />Authoritative asset inventory</div>
          <h1>Camera Registry</h1>
          <p>Onboard, discover and audit cameras across departments, vendors and operational boundaries.</p>
        </div>
        <div className="page-header__actions">
          <span className="sync-stamp"><Satellite aria-hidden="true" size={14} /><span>Last synchronized<strong>{lastSynchronized}</strong></span></span>
          <button type="button" className="icon-button" aria-label="Refresh registry" onClick={refreshAll} disabled={listLoading}><RefreshCw className={listLoading ? "spin" : undefined} size={17} /></button>
          <button type="button" className="button button--secondary" onClick={() => setDepartmentOpen(true)}><Building2 aria-hidden="true" size={16} /> Add department</button>
          <button type="button" className="button button--secondary" onClick={() => setImportOpen(true)}><FileUp aria-hidden="true" size={16} /> Bulk import</button>
          <button type="button" className="button button--primary" onClick={() => setOnboardOpen(true)}><Plus aria-hidden="true" size={17} /> Register camera</button>
        </div>
      </header>

      <SummaryCards statistics={statistics} loading={statsLoading} />

      <section className="registry-workspace">
        <header className="workspace-header">
          <div><span className="workspace-header__icon"><ShieldCheck aria-hidden="true" size={18} /></span><span><strong>Federated asset operations</strong><small>Live registry metadata · no central video transport</small></span></div>
          <span className="workspace-header__status"><i /> API-backed inventory</span>
        </header>
        <CameraFilters value={filters} departments={departments} onChange={setFilters} resultCount={cameraPage?.total} />
        <div className="workspace-split">
          <section className="workspace-panel workspace-panel--map">
            <header><div><span className="panel-kicker">Geospatial coverage</span><h2>Operational map</h2></div><small>Clustered by viewport</small></header>
            <CameraMap data={geoJson} loading={mapLoading} error={mapError} selectedId={selectedCameraId} onSelect={onSelectCamera} onRetry={refresh} />
          </section>
          <section className="workspace-panel workspace-panel--table">
            <header><div><span className="panel-kicker">Normalized metadata</span><h2>Camera inventory</h2></div><small>{cameraPage ? `${cameraPage.total.toLocaleString("en-IN")} assets` : "Awaiting registry"}</small></header>
            <CameraTable data={cameraPage} loading={listLoading} error={listError} selectedId={selectedCameraId} onSelect={onSelectCamera} onRetry={refresh} onPageChange={setPage} />
          </section>
        </div>
      </section>

      <OnboardCameraModal
        open={onboardOpen}
        departments={departments}
        onDepartmentCreated={(department) => {
          onDepartmentCreated(department);
          setNotice(`${department.name} is now available for camera registration.`);
        }}
        onClose={() => setOnboardOpen(false)}
        onCreated={(camera) => {
          onSelectCamera(cameraId(camera));
          setNotice(`${camera.camera_code} was registered successfully.`);
          refreshAll();
        }}
      />
      <AddDepartmentModal
        open={departmentOpen}
        onClose={() => setDepartmentOpen(false)}
        onCreated={(department) => {
          onDepartmentCreated(department);
          setNotice(`${department.name} was added to the registry.`);
        }}
      />
      <CsvImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={(result) => {
          const changed = (result.created ?? 0) + (result.updated ?? 0);
          const failed = result.failed ?? 0;
          const skipped = result.skipped ?? 0;
          setNotice(result.replayed
            ? "Previous import result replayed; no duplicate changes were made."
            : failed > 0
              ? `${changed} camera records applied; ${failed} row${failed === 1 ? " needs" : "s need"} correction.`
              : changed === 0 && skipped > 0
                ? `${skipped} duplicate row${skipped === 1 ? " was" : "s were"} skipped; no records changed.`
                : `CSV import completed: ${changed} camera record${changed === 1 ? "" : "s"} applied.`);
          refreshAll();
        }}
      />
      <CameraDetailDrawer cameraId={selectedCameraId} onClose={() => onSelectCamera(null)} />
      {notice ? <div className="toast" role="status"><ShieldCheck aria-hidden="true" size={17} />{notice}</div> : null}
    </div>
  );
}
