import type { LatLngBoundsExpression, LatLngExpression } from "leaflet";
import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  CircleDotDashed,
  Crosshair,
  Layers3,
  LoaderCircle,
  MapPinned,
  RadioTower,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Circle, CircleMarker, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import { advancedApi, ApiError } from "../lib/api";
import { formatTimestamp, titleCase } from "../lib/format";
import type { CoverageAnalysis, CoverageWhatIf } from "../types/advanced";

const GUJARAT_CENTER: LatLngExpression = [22.72, 71.64];
const tileUrl = import.meta.env.VITE_MAP_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const tileAttribution = import.meta.env.VITE_MAP_ATTRIBUTION || "&copy; OpenStreetMap contributors";

export function CoverageIntelligencePage() {
  const [analysis, setAnalysis] = useState<CoverageAnalysis | null>(null);
  const [simulation, setSimulation] = useState<CoverageWhatIf | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setAnalysis(await advancedApi.coverage(signal));
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof ApiError ? cause.message : "Coverage intelligence is unavailable.");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [load]);

  const analyze = async () => {
    setBusy(true); setError(null); setSimulation(null);
    try { setAnalysis(await advancedApi.analyzeCoverage()); }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : "Coverage analysis failed."); }
    finally { setBusy(false); }
  };
  const whatIf = async (cameraId: string) => {
    setBusy(true); setError(null);
    try { setSimulation(await advancedApi.coverageWhatIf(cameraId)); }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : "Simulation failed."); }
    finally { setBusy(false); }
  };

  const metrics = analysis?.metrics ?? {};
  return <div className="advanced-page coverage-page">
    <section className="advanced-masthead coverage-masthead">
      <div><span className="advanced-emblem"><MapPinned size={25} /><i /></span><span><small>P-S04 · Planning intelligence</small><h1>Coverage Intelligence</h1><p>Registry-backed resilience gaps, critical nodes and transparent deployment candidates.</p></span></div>
      <button className="button button--primary" type="button" disabled={busy} onClick={() => void analyze()}>{busy ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}Run fresh analysis</button>
    </section>
    {error ? <div className="advanced-alert"><TriangleAlert size={16} />{error}</div> : null}
    <section className="coverage-kpis"><CoverageKpi icon={Camera} label="Registered nodes" value={analysis?.camera_count ?? 0} tone="neutral" /><CoverageKpi icon={CheckCircle2} label="Operational nodes" value={analysis?.operational_count ?? 0} tone="healthy" /><CoverageKpi icon={AlertTriangle} label="Temporary gaps" value={metrics.temporary_gaps ?? 0} tone="critical" /><CoverageKpi icon={CircleDotDashed} label="Permanent gaps" value={metrics.permanent_gaps ?? 0} tone="warning" /><CoverageKpi icon={RadioTower} label="Critical nodes" value={metrics.critical_nodes ?? 0} tone="signal" /><CoverageKpi icon={Sparkles} label="Candidate areas" value={metrics.deployment_candidates ?? 0} tone="cyan" /></section>
    <div className="coverage-layout">
      <section className="coverage-map-panel"><header><div><span className="panel-kicker">Geospatial resilience canvas</span><h2>State coverage posture</h2></div><div className="coverage-legend"><span><i className="temporary" />Temporary outage</span><span><i className="permanent" />Permanent estimate</span><span><i className="candidate" />Candidate area</span></div></header><CoverageMap analysis={analysis} simulation={simulation} /><footer><ShieldCheck size={14} />Location estimates do not assert road visibility or exact installation coordinates.</footer></section>
      <aside className="coverage-side">
        <section className="critical-node-list"><header><div><span className="panel-kicker">Single points of failure</span><h2>Critical nodes</h2></div><b>{analysis?.critical_nodes.length ?? 0}</b></header><div>{analysis?.critical_nodes.map((item) => <article key={item.camera.id}><span><i /><strong>{item.camera.camera_code}</strong><small>{item.camera.camera_name}</small><em>{item.nearest_backup_distance_m == null ? "No backup located" : `${(item.nearest_backup_distance_m / 1000).toFixed(1)} km to backup`}</em></span><button type="button" disabled={busy} onClick={() => void whatIf(item.camera.id)}><Crosshair size={14} />Simulate outage</button></article>)}</div>{!analysis?.critical_nodes.length ? <div className="advanced-empty compact"><CheckCircle2 size={22} /><strong>No critical node under this radius</strong></div> : null}</section>
        {simulation ? <section className={`coverage-simulation coverage-simulation--${simulation.critical_gap_created ? "critical" : "contained"}`}><header><span><Crosshair size={16} />What-if simulation</span><b>NO STATE CHANGED</b></header><h3>{simulation.camera.camera_code} removed</h3><div><span><small>Coverage at risk</small><strong>{(simulation.estimated_coverage_lost_radius_m / 1000).toFixed(1)} km radius</strong></span><span><small>Nearest backup</small><strong>{simulation.nearest_backup?.camera_code ?? "None"}</strong></span><span><small>Critical gap</small><strong>{simulation.critical_gap_created ? "Created" : "Contained"}</strong></span><span><small>Active pursuits</small><strong>{simulation.affected_investigation_ids.length}</strong></span></div><p>{simulation.assumptions.join(" ")}</p></section> : <section className="coverage-simulation coverage-simulation--idle"><Layers3 size={25} /><strong>Resilience simulator</strong><p>Select a critical node to see estimated loss and investigation impact without changing operational state.</p></section>}
      </aside>
    </div>
    <div className="coverage-bottom">
      <section className="gap-register"><header><div><span className="panel-kicker">Explainable findings</span><h2>Coverage gap register</h2></div><b>{analysis?.gaps.length ?? 0}</b></header>{analysis?.gaps.map((item) => <article key={item.id}><i className={item.gap_type} /><span><strong>{titleCase(item.gap_type)} · {titleCase(item.severity)}</strong><p>{item.explanation}</p><small>{titleCase(item.confidence_basis)} · {(item.radius_m / 1000).toFixed(1)} km estimated radius</small></span></article>)}{loading ? <div className="advanced-loading"><LoaderCircle className="spin" size={18} />Computing registry-backed coverage…</div> : !analysis?.gaps.length ? <div className="advanced-empty compact"><CheckCircle2 size={22} /><strong>No gap crossed the configured planning threshold</strong></div> : null}</section>
      <section className="deployment-register"><header><div><span className="panel-kicker">Field planning shortlist</span><h2>Deployment candidates</h2></div><RadioTower size={18} /></header>{analysis?.deployment_candidates.map((item, index) => <article key={item.id}><b>{String(index + 1).padStart(2, "0")}</b><span><strong>{item.area_label}</strong><p>{item.reasons[0]}</p><small>{item.assumption}</small></span><em>{item.priority}</em></article>)}</section>
    </div>
    {analysis ? <div className="advanced-disclosure"><ShieldCheck size={15} /><span><strong>Analysis {formatTimestamp(analysis.created_at)} · {analysis.duration_ms.toFixed(1)} ms.</strong> {analysis.assumptions.join(" ")}</span></div> : null}
  </div>;
}

function CoverageKpi({ icon: Icon, label, value, tone }: { icon: typeof Camera; label: string; value: number; tone: string }) { return <div className={`coverage-kpi coverage-kpi--${tone}`}><Icon size={17} /><span><small>{label}</small><strong>{value.toLocaleString("en-IN")}</strong></span></div>; }

function CoverageMap({ analysis, simulation }: { analysis: CoverageAnalysis | null; simulation: CoverageWhatIf | null }) {
  const points = useMemo(() => analysis ? [...analysis.gaps.map((item) => [item.latitude, item.longitude] as [number, number]), ...analysis.deployment_candidates.map((item) => [item.latitude, item.longitude] as [number, number]), ...analysis.critical_nodes.map((item) => [item.camera.latitude, item.camera.longitude] as [number, number])] : [], [analysis]);
  return <div className="coverage-map"><MapContainer center={GUJARAT_CENTER} zoom={7} minZoom={5} maxZoom={18}><TileLayer attribution={tileAttribution} url={tileUrl} />{analysis?.gaps.map((item) => <Circle key={item.id} center={[item.latitude, item.longitude]} radius={Math.min(item.radius_m, 30000)} pathOptions={{ color: item.gap_type === "temporary" ? "#ed6a72" : "#f1b858", fillColor: item.gap_type === "temporary" ? "#b93645" : "#9b6721", fillOpacity: .14, weight: 2, dashArray: item.gap_type === "permanent" ? "7 7" : undefined }}><Tooltip><strong>{titleCase(item.gap_type)} coverage gap</strong><br/>{item.explanation}</Tooltip></Circle>)}{analysis?.deployment_candidates.map((item) => <CircleMarker key={item.id} center={[item.latitude, item.longitude]} radius={7} pathOptions={{ color: "#42e0d7", fillColor: "#42e0d7", fillOpacity: .7, weight: 2 }}><Tooltip><strong>{item.area_label}</strong><br/>{item.assumption}</Tooltip></CircleMarker>)}{analysis?.critical_nodes.map((item) => <CircleMarker key={item.camera.id} center={[item.camera.latitude, item.camera.longitude]} radius={9} pathOptions={{ color: "#eaf5f7", fillColor: "#163d50", fillOpacity: .8, weight: 2 }}><Tooltip><strong>{item.camera.camera_code}</strong><br/>{item.reason}</Tooltip></CircleMarker>)}{simulation ? <Circle center={[simulation.camera.latitude, simulation.camera.longitude]} radius={simulation.estimated_coverage_lost_radius_m} pathOptions={{ color: "#ff445f", fillColor: "#ff445f", fillOpacity: .13, weight: 3, dashArray: "4 6" }} /> : null}{points.length ? <FitCoverage points={points} /> : null}</MapContainer></div>;
}

function FitCoverage({ points }: { points: Array<[number, number]> }) {
  const map = useMap();
  const signature = points.map((item) => item.join(",")).join("|");
  useEffect(() => {
    const values = signature.split("|").filter(Boolean).map((item) => item.split(",").map(Number) as [number, number]);
    if (values.length === 1) map.setView(values[0], 11);
    else if (values.length > 1) map.fitBounds(values as LatLngBoundsExpression, { padding: [45, 45], maxZoom: 11 });
  }, [map, signature]);
  return null;
}
