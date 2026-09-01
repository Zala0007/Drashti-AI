import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  Building2,
  Camera,
  CheckCircle2,
  Database,
  MapPinned,
  RefreshCw,
  Route,
  Satellite,
  ShieldAlert,
  Cable,
} from "lucide-react";
import { useMemo } from "react";
import { cameraHealth, cameraId, departmentLabel, formatTimestamp } from "../lib/format";
import type { Camera as CameraRecord, CameraGeoJson, CameraStatistics, Department } from "../types/registry";
import { CameraMap } from "../components/CameraMap";
import { StatusBadge } from "../components/StatusBadge";
import type { FederationStatistics } from "../types/federation";

interface CommandCentrePageProps {
  statistics: CameraStatistics | null;
  geoJson: CameraGeoJson | null;
  departments: Department[];
  attentionCameras: CameraRecord[];
  loading: boolean;
  error: string | null;
  lastSynchronized: string;
  selectedCameraId: string | null;
  onSelectCamera: (id: string) => void;
  onRetry: () => void;
  onOpenGis: () => void;
  federationStatistics: FederationStatistics | null;
  federationConnected: boolean | null;
  onOpenFederation: () => void;
}

export function CommandCentrePage({
  statistics,
  geoJson,
  departments,
  attentionCameras,
  loading,
  error,
  lastSynchronized,
  selectedCameraId,
  onSelectCamera,
  onRetry,
  onOpenGis,
  federationStatistics,
  federationConnected,
  onOpenFederation,
}: CommandCentrePageProps) {
  const mappedCount = geoJson?.number_matched ?? geoJson?.features.length ?? 0;
  const healthAttention = (statistics?.offline ?? 0) + (statistics?.degraded ?? 0);
  const districts = useMemo(
    () => new Set((geoJson?.features ?? []).map((feature) => feature.properties.district).filter(Boolean)).size,
    [geoJson],
  );
  const coverage = useMemo(() => {
    if (statistics?.by_department?.length) {
      return [...statistics.by_department]
        .sort((left, right) => right.count - left.count)
        .map((item) => ({ name: item.department_name, code: item.department_code, count: item.count }));
    }
    const counts = new Map<string, number>();
    (geoJson?.features ?? []).forEach((feature) => {
      const name = feature.properties.department_name ?? "Unassigned";
      counts.set(name, (counts.get(name) ?? 0) + 1);
    });
    return [...counts.entries()].map(([name, count]) => ({ name, code: "—", count })).sort((a, b) => b.count - a.count);
  }, [geoJson, statistics]);
  const coverageMax = Math.max(1, ...coverage.map((item) => item.count));

  return (
    <div className="page command-page">
      <header className="hero-header">
        <div>
          <div className="page-header__context"><span>Statewide CCTV network</span><i />Registry and GIS operational</div>
          <h1>Unified CCTV Intelligence Platform</h1>
          <p>Live, API-backed visibility across Gujarat’s federated camera estate.</p>
        </div>
        <div className="hero-header__actions">
          <span className="sync-stamp"><Satellite aria-hidden="true" size={15} /><span>Last synchronized<strong>{lastSynchronized}</strong></span></span>
          <button type="button" className="button button--secondary" onClick={onRetry} disabled={loading}>
            <RefreshCw className={loading ? "spin" : undefined} aria-hidden="true" size={16} /> Refresh posture
          </button>
        </div>
      </header>

      {error ? (
        <div className="command-error" role="alert"><ShieldAlert aria-hidden="true" size={18} /><span><strong>Operational data is temporarily unavailable</strong><small>{error}</small></span><button type="button" onClick={onRetry}>Retry</button></div>
      ) : null}

      <section className="command-kpis" aria-label="Registry key performance indicators">
        <CommandKpi icon={Camera} label="Registered cameras" value={statistics?.total} note="Authoritative inventory" loading={loading} />
        <CommandKpi icon={CheckCircle2} label="Online cameras" value={statistics?.online} note={statistics?.total ? `${Math.round((statistics.online / statistics.total) * 100)}% of registry` : "No registered assets"} tone="healthy" loading={loading} />
        <CommandKpi icon={AlertTriangle} label="Health attention" value={statistics ? healthAttention : undefined} note={`${statistics?.offline ?? 0} offline · ${statistics?.degraded ?? 0} degraded`} tone={healthAttention > 0 ? "warning" : "healthy"} loading={loading} />
        <CommandKpi icon={Cable} label="Reachable probes" value={federationConnected ? federationStatistics?.reachable ?? 0 : undefined} note={federationConnected ? `${federationStatistics?.reachable ?? 0} verified RTSP; ${federationStatistics?.total ?? 0} profiles` : "Federation service pending"} tone={federationConnected ? "healthy" : "intelligence"} loading={federationConnected === null} />
        <CommandKpi icon={Building2} label="Departments" value={departments.length} note="Onboarded source owners" loading={loading} />
        <CommandKpi icon={MapPinned} label="Mapped locations" value={mappedCount} note={`${districts} district${districts === 1 ? "" : "s"} represented`} loading={loading} />
      </section>

      <section className="command-grid">
        <article className="command-panel command-panel--map">
          <header className="command-panel__header">
            <div><span className="panel-kicker">Statewide operational picture</span><h2>Camera network overview</h2></div>
            <button type="button" className="text-action" onClick={onOpenGis}>Open GIS Operations <span aria-hidden="true">→</span></button>
          </header>
          <CameraMap
            data={geoJson}
            loading={loading}
            error={error}
            selectedId={selectedCameraId}
            onSelect={onSelectCamera}
            onRetry={onRetry}
            mode="overview"
          />
        </article>

        <aside className="command-panel command-panel--attention">
          <header className="command-panel__header">
            <div><span className="panel-kicker">Actionable registry health</span><h2>Operational attention</h2></div>
            <span className={`attention-count${healthAttention > 0 ? " attention-count--warning" : ""}`}>{healthAttention}</span>
          </header>
          <div className="attention-list">
            {loading && attentionCameras.length === 0 ? <AttentionSkeleton /> : null}
            {!loading && healthAttention === 0 ? (
              <div className="attention-empty"><CheckCircle2 aria-hidden="true" size={27} /><strong>No offline or degraded assets</strong><p>Health status is derived from registry heartbeats.</p></div>
            ) : null}
            {attentionCameras.map((camera) => (
              <button type="button" key={cameraId(camera)} className="attention-item" onClick={() => onSelectCamera(cameraId(camera))}>
                <span className={`attention-item__cue attention-item__cue--${cameraHealth(camera)}`}>{cameraHealth(camera) === "offline" ? "×" : "!"}</span>
                <span className="attention-item__body"><strong>{camera.camera_name}</strong><small>{camera.camera_code} · {camera.city || camera.district}</small><em>{departmentLabel(camera)}</em></span>
                <span className="attention-item__status"><StatusBadge value={cameraHealth(camera)} /><small>{formatTimestamp(camera.last_heartbeat)}</small></span>
              </button>
            ))}
            {!loading && healthAttention > attentionCameras.length ? <p className="attention-overflow">Showing {attentionCameras.length} of {healthAttention} affected cameras. Use GIS health filters for the complete set.</p> : null}
          </div>
        </aside>
      </section>

      <section className="command-lower-grid">
        <article className="command-panel coverage-panel">
          <header className="command-panel__header"><div><span className="panel-kicker">Federation footprint</span><h2>Department coverage</h2></div><small>{coverage.length} reporting</small></header>
          <div className="coverage-list">
            {coverage.length === 0 && !loading ? <div className="panel-empty"><Building2 size={23} /><span><strong>No department coverage yet</strong><small>Onboard a camera to establish coverage.</small></span></div> : null}
            {coverage.slice(0, 6).map((item) => (
              <div className="coverage-row" key={`${item.code}-${item.name}`}>
                <span className="coverage-row__identity"><b>{item.code}</b><span><strong>{item.name}</strong><small>{item.count.toLocaleString("en-IN")} cameras</small></span></span>
                <span className="coverage-row__bar"><i style={{ width: `${Math.max(4, (item.count / coverageMax) * 100)}%` }} /></span>
              </div>
            ))}
          </div>
          <footer className="coverage-footer">
            <span><Database size={15} /> {statistics?.total?.toLocaleString("en-IN") ?? "—"} normalized assets</span>
            <span><MapPinned size={15} /> {districts} mapped districts</span>
          </footer>
        </article>

        <article className="command-panel intelligence-readiness">
          <header className="command-panel__header"><div><span className="panel-kicker">Transparent capability posture</span><h2>Intelligence pipeline readiness</h2></div><button type="button" className="next-module-chip next-module-chip--action" onClick={onOpenFederation}>Open P0.3</button></header>
          <div className="readiness-flow">
            <ReadinessStep icon={Database} title="Registry + GIS" status="Operational" complete />
            <span aria-hidden="true">→</span>
            <ReadinessStep icon={Activity} title="Stream federation" status={federationConnected ? `${federationStatistics?.reachable ?? 0} reachable probes` : "Service pending"} complete={Boolean(federationConnected && federationStatistics?.reachable)} />
            <span aria-hidden="true">→</span>
            <ReadinessStep icon={BrainCircuit} title="ANPR + watchlists" status="Evidence review ready" complete />
            <span aria-hidden="true">→</span>
            <ReadinessStep icon={Route} title="Vehicle route" status="Investigation workspace ready" complete />
          </div>
          <div className="readiness-notice"><ShieldAlert size={17} /><p><strong>Presentation scenarios are explicitly disclosed.</strong> Operational detections remain source-linked, confidence-scored, and subject to human review.</p></div>
        </article>
      </section>
    </div>
  );
}

function CommandKpi({ icon: Icon, label, value, note, tone = "neutral", loading }: { icon: typeof Camera; label: string; value?: number; note: string; tone?: "neutral" | "healthy" | "warning" | "intelligence"; loading: boolean }) {
  return <article className={`command-kpi command-kpi--${tone}`}><span className="command-kpi__icon"><Icon aria-hidden="true" size={20} /></span><span><small>{label}</small>{loading && value === undefined ? <i className="skeleton skeleton--number" /> : <strong>{typeof value === "number" ? value.toLocaleString("en-IN") : "—"}</strong>}<em>{note}</em></span></article>;
}

function ReadinessStep({ icon: Icon, title, status, complete = false }: { icon: typeof Database; title: string; status: string; complete?: boolean }) {
  return <div className={`readiness-step${complete ? " readiness-step--complete" : ""}`}><Icon aria-hidden="true" size={19} /><span><strong>{title}</strong><small>{status}</small></span></div>;
}

function AttentionSkeleton() {
  return <>{[0, 1, 2].map((item) => <div key={item} className="attention-item attention-item--skeleton"><i className="skeleton" /><span><i className="skeleton" /><i className="skeleton" /></span></div>)}</>;
}
