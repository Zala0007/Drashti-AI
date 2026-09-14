import {
  Activity, AlertTriangle, ArrowUpRight, BrainCircuit, Building2, Cable,
  Camera, CheckCircle2, Database, MapPinned, Radio, RefreshCw, Route,
  Satellite, ScanSearch, ShieldAlert,
} from "lucide-react";
import { useMemo } from "react";
import { cameraHealth, cameraId, departmentLabel, formatTimestamp } from "../lib/format";
import type { Camera as CameraRecord, CameraGeoJson, CameraStatistics, Department } from "../types/registry";
import { CameraMap } from "../components/CameraMap";
import { StatusBadge } from "../components/StatusBadge";
import type { FederationStatistics } from "../types/federation";
import "./command-centre.css";

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

const capabilities = [
  { icon: ScanSearch, title: "Visual search", detail: "Find a moment in the footage", href: "#/visual", label: "01 / Discover" },
  { icon: Route, title: "Vehicle pursuit", detail: "Connect sightings across cameras", href: "#/investigation", label: "02 / Investigate" },
  { icon: BrainCircuit, title: "Video analytics", detail: "Turn video into searchable evidence", href: "#/ai", label: "03 / Understand" },
  { icon: Radio, title: "Live operations", detail: "Bring your camera feeds together", href: "#/live", label: "04 / Respond" },
];

export function CommandCentrePage({
  statistics, geoJson, departments, attentionCameras, loading, error,
  lastSynchronized, selectedCameraId, onSelectCamera, onRetry, onOpenGis,
  federationStatistics, federationConnected, onOpenFederation,
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
    return [...counts.entries()].map(([name, count]) => ({ name, code: "--", count })).sort((a, b) => b.count - a.count);
  }, [geoJson, statistics]);
  const coverageMax = Math.max(1, ...coverage.map((item) => item.count));

  return (
    <div className="page command-page command-workspace">
      <header className="command-intro">
        <div className="command-intro__copy">
          <span className="command-eyebrow"><span aria-hidden="true" /> Gujarat / Command centre</span>
          <h1>Every camera.<br /><em>One clear picture.</em></h1>
          <p>Find the signal. Follow the evidence. Coordinate your response.</p>
        </div>
        <div className="command-intro__status">
          <span className={`command-connection${error ? " command-connection--error" : loading ? " command-connection--pending" : ""}`}>
            <span aria-hidden="true" />{error ? "Registry connection interrupted" : loading ? "Synchronizing registry" : "Connected to camera registry"}
          </span>
          <span className="command-sync"><Satellite aria-hidden="true" size={15} /><span>Last synchronized<strong>{lastSynchronized}</strong></span></span>
          <button type="button" className="command-refresh" onClick={onRetry} disabled={loading}>
            <RefreshCw className={loading ? "spin" : undefined} aria-hidden="true" size={15} />{loading ? "Refreshing..." : "Refresh network"}
          </button>
        </div>
      </header>

      <nav className="command-capabilities" aria-label="Intelligence workspaces">
        {capabilities.map(({ icon: Icon, title, detail, href, label }) => (
          <a className="capability-link" key={href} href={href}>
            <span className="capability-link__top"><small>{label}</small><ArrowUpRight aria-hidden="true" size={17} /></span>
            <span className="capability-link__title"><Icon aria-hidden="true" size={22} /><strong>{title}</strong></span>
            <span className="capability-link__detail">{detail}</span>
          </a>
        ))}
      </nav>

      {error ? (
        <div className="ops-error" role="alert"><ShieldAlert aria-hidden="true" size={18} /><span><strong>Operational data is temporarily unavailable</strong><small>{error}</small></span><button type="button" onClick={onRetry}>Retry</button></div>
      ) : null}

      <section className="ops-metrics" aria-label="Registry key performance indicators">
        <CommandKpi icon={Camera} label="Registered cameras" value={statistics?.total} note="Unified camera inventory" loading={loading} />
        <CommandKpi icon={CheckCircle2} label="Online cameras" value={statistics?.online} note={statistics?.total ? `${Math.round((statistics.online / statistics.total) * 100)}% of the network` : "No registered assets"} tone="healthy" loading={loading} />
        <CommandKpi icon={AlertTriangle} label="Need attention" value={statistics ? healthAttention : undefined} note={`${statistics?.offline ?? 0} offline / ${statistics?.degraded ?? 0} degraded`} tone={healthAttention > 0 ? "warning" : "healthy"} loading={loading} />
        <CommandKpi icon={Cable} label="Reachable probes" value={federationConnected ? federationStatistics?.reachable ?? 0 : undefined} note={federationConnected ? `${federationStatistics?.total ?? 0} stream profiles` : "Federation service pending"} tone={federationConnected ? "healthy" : "neutral"} loading={federationConnected === null} />
        <CommandKpi icon={Building2} label="Departments" value={departments.length} note="Connected source owners" loading={loading} />
        <CommandKpi icon={MapPinned} label="Mapped locations" value={mappedCount} note={`${districts} district${districts === 1 ? "" : "s"} represented`} loading={loading} />
      </section>

      <section className="ops-overview-grid">
        <article className="ops-panel ops-panel--map">
          <header className="ops-panel__header">
            <div><span className="ops-kicker">01 / The operational picture</span><h2>Your network, in view</h2></div>
            <button type="button" className="ops-link" onClick={onOpenGis}>Explore GIS <ArrowUpRight aria-hidden="true" size={15} /></button>
          </header>
          <CameraMap data={geoJson} loading={loading} error={error} selectedId={selectedCameraId} onSelect={onSelectCamera} onRetry={onRetry} mode="overview" />
          <footer className="ops-map-caption"><span><MapPinned aria-hidden="true" size={14} /> Gujarat camera network</span><span>Select a camera to inspect its details</span></footer>
        </article>

        <aside className="ops-panel ops-panel--attention">
          <header className="ops-panel__header">
            <div><span className="ops-kicker">02 / Focus your response</span><h2>Operational attention</h2></div>
            <span className={`ops-attention-count${healthAttention > 0 ? " ops-attention-count--warning" : ""}`}>{statistics ? healthAttention : "--"}</span>
          </header>
          <div className="ops-attention-list">
            {loading && attentionCameras.length === 0 ? <AttentionSkeleton /> : null}
            {!loading && !error && statistics && healthAttention === 0 ? (
              <div className="ops-empty"><CheckCircle2 aria-hidden="true" size={30} /><strong>Your network is in good shape</strong><p>No offline or degraded assets reported by registry heartbeats.</p></div>
            ) : null}
            {!loading && !statistics ? (
              <div className="ops-empty ops-empty--neutral"><Activity aria-hidden="true" size={28} /><strong>Waiting for network health</strong><p>Camera status will appear when the registry is available.</p></div>
            ) : null}
            {attentionCameras.map((camera) => (
              <button type="button" key={cameraId(camera)} className={`ops-attention-item${selectedCameraId === cameraId(camera) ? " ops-attention-item--selected" : ""}`} onClick={() => onSelectCamera(cameraId(camera))}>
                <span className="ops-attention-item__top"><strong>{camera.camera_name}</strong><StatusBadge value={cameraHealth(camera)} /></span>
                <span className="ops-attention-item__location">{camera.camera_code}<span aria-hidden="true"> / </span>{camera.city || camera.district}</span>
                <span className="ops-attention-item__meta"><span>{departmentLabel(camera)}</span><ArrowUpRight aria-hidden="true" size={14} /></span>
                <small>Last heartbeat: {formatTimestamp(camera.last_heartbeat)}</small>
              </button>
            ))}
            {!loading && healthAttention > attentionCameras.length ? <p className="ops-attention-overflow">Showing {attentionCameras.length} of {healthAttention} affected cameras. Open GIS to filter the complete network.</p> : null}
          </div>
          <button className="ops-attention-footer" type="button" onClick={onOpenGis}>Review camera health <ArrowUpRight aria-hidden="true" size={15} /></button>
        </aside>
      </section>

      <section className="ops-detail-grid">
        <article className="ops-panel">
          <header className="ops-panel__header"><div><span className="ops-kicker">03 / Connected departments</span><h2>One network. Shared visibility.</h2></div><small>{coverage.length} reporting</small></header>
          <div className="ops-coverage-list">
            {coverage.length === 0 ? <div className="ops-empty ops-empty--neutral"><Building2 aria-hidden="true" size={23} /><strong>{loading ? "Loading department coverage" : "No department coverage yet"}</strong><p>{loading ? "Connecting to the camera registry." : "Onboard a camera to establish coverage."}</p></div> : null}
            {coverage.slice(0, 6).map((item) => (
              <div className="ops-coverage-row" key={`${item.code}-${item.name}`}>
                <span className="ops-coverage-row__identity"><b>{item.code}</b><strong title={item.name}>{item.name}</strong></span>
                <span className="ops-coverage-row__bar"><i style={{ width: `${Math.max(4, (item.count / coverageMax) * 100)}%` }} /></span>
                <span className="ops-coverage-row__count">{item.count.toLocaleString("en-IN")}</span>
              </div>
            ))}
          </div>
          <footer className="ops-coverage-footer"><span><Database aria-hidden="true" size={14} />{statistics?.total?.toLocaleString("en-IN") ?? "--"} normalized assets</span><span>{districts} mapped districts</span></footer>
        </article>

        <article className="ops-panel">
          <header className="ops-panel__header"><div><span className="ops-kicker">04 / From source to insight</span><h2>The intelligence pipeline</h2></div><button type="button" className="ops-link" onClick={onOpenFederation}>Federation <ArrowUpRight aria-hidden="true" size={15} /></button></header>
          <div className="ops-pipeline">
            <ReadinessStep icon={Database} number="01" title="Connect" detail="Registry + GIS" status={error ? "Connection interrupted" : loading ? "Synchronizing" : "Registry connected"} complete={!error && !loading && Boolean(statistics)} />
            <ReadinessStep icon={Activity} number="02" title="Observe" detail="Stream federation" status={federationConnected ? `${federationStatistics?.reachable ?? 0} reachable probes` : "Service pending"} complete={Boolean(federationConnected && federationStatistics?.reachable)} />
            <ReadinessStep icon={BrainCircuit} number="03" title="Understand" detail="ANPR + watchlists" status="Evidence review workspace" complete />
            <ReadinessStep icon={Route} number="04" title="Investigate" detail="Vehicle route" status="Investigation workspace" complete />
          </div>
          <div className="ops-evidence-note"><ShieldAlert aria-hidden="true" size={16} /><p>Evidence stays linked to its source. Confidence and human review stay part of the decision. Presentation scenarios are labeled.</p></div>
        </article>
      </section>
    </div>
  );
}

function CommandKpi({ icon: Icon, label, value, note, tone = "neutral", loading }: { icon: typeof Camera; label: string; value?: number; note: string; tone?: "neutral" | "healthy" | "warning"; loading: boolean }) {
  return <article className={`ops-metric ops-metric--${tone}`}><span className="ops-metric__label"><Icon aria-hidden="true" size={15} /><small>{label}</small></span>{loading && value === undefined ? <i className="skeleton skeleton--number" /> : <strong>{typeof value === "number" ? value.toLocaleString("en-IN") : "--"}</strong>}<em>{note}</em></article>;
}

function ReadinessStep({ icon: Icon, number, title, detail, status, complete = false }: { icon: typeof Database; number: string; title: string; detail: string; status: string; complete?: boolean }) {
  return <div className={`ops-pipeline-step${complete ? " ops-pipeline-step--complete" : ""}`}><span className="ops-pipeline-step__icon"><Icon aria-hidden="true" size={20} /><small>{number}</small></span><strong>{title}</strong><span>{detail}</span><small className="ops-pipeline-step__status"><i aria-hidden="true" />{status}</small></div>;
}

function AttentionSkeleton() {
  return <>{[0, 1, 2].map((item) => <div key={item} className="ops-attention-skeleton"><i className="skeleton" /><i className="skeleton" /><i className="skeleton" /></div>)}</>;
}
