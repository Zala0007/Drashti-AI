import L, { type LatLngBoundsExpression, type LatLngExpression } from "leaflet";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  CheckCircle2,
  ChevronRight,
  CircleDotDashed,
  Crosshair,
  FileSearch,
  Fingerprint,
  Gauge,
  History,
  LocateFixed,
  Navigation,
  OctagonPause,
  Orbit,
  Play,
  Radar,
  RefreshCw,
  Route,
  ScanSearch,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Target,
  TimerReset,
  Waypoints,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import { ApiError, investigationApi } from "../lib/api";
import { VehicleReIDPanel } from "../components/VehicleReIDPanel";
import { formatTimestamp, relativeTime, titleCase } from "../lib/format";
import type {
  InvestigationCandidate,
  InvestigationCase,
  InvestigationConfidence,
  InvestigationObservation,
  InvestigationWorkspace,
  PredictionBacktest,
} from "../types/investigation";

const GUJARAT_CENTER: LatLngExpression = [22.72, 71.64];
const tileUrl = import.meta.env.VITE_MAP_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const tileAttribution = import.meta.env.VITE_MAP_ATTRIBUTION || "&copy; OpenStreetMap contributors";

const safeMessage = (error: unknown) => error instanceof ApiError
  ? error.message
  : "The investigation engine could not complete this operation.";

const statusIcon = (status: string) => status === "confirmed" ? BadgeCheck : status === "rejected" ? X : CircleDotDashed;
const eta = (candidate: InvestigationCandidate) => `${Math.max(1, Math.round(candidate.eta_min_seconds / 60))}–${Math.max(1, Math.round(candidate.eta_max_seconds / 60))} min`;

export function SpecialInvestigationPage() {
  const [cases, setCases] = useState<InvestigationCase[]>([]);
  const [workspace, setWorkspace] = useState<InvestigationWorkspace | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [plate, setPlate] = useState("GJ01AB1234");
  const [priority, setPriority] = useState<"critical" | "high" | "standard">("high");
  const [reason, setReason] = useState("Authorized vehicle pursuit and route intelligence assessment");
  const [district, setDistrict] = useState("");
  const [loading, setLoading] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demoDisclosure, setDemoDisclosure] = useState<string | null>(null);
  const [lastLiveUpdate, setLastLiveUpdate] = useState<Date | null>(null);
  const [backtest, setBacktest] = useState<PredictionBacktest | null>(null);

  const loadCases = useCallback(async (signal?: AbortSignal) => {
    const result = await investigationApi.list(signal);
    setCases(result.items);
    return result.items;
  }, []);

  const openCase = useCallback(async (id: string, signal?: AbortSignal) => {
    const result = await investigationApi.workspace(id, signal);
    setWorkspace(result);
    setSelectedCandidateId((current) => result.candidates.some((item) => item.id === current)
      ? current
      : result.candidates[0]?.id ?? null);
    setLastLiveUpdate(new Date());
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    loadCases(controller.signal)
      .then((items) => items[0] ? openCase(items[0].id, controller.signal) : undefined)
      .catch((cause) => {
        if (!(cause instanceof DOMException && cause.name === "AbortError")) setError(safeMessage(cause));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [loadCases, openCase]);

  const activeCaseId = workspace?.case.id;
  const activeCaseStatus = workspace?.case.status;
  const acceptedObservationCount = workspace?.observations.filter((item) =>
    item.status === "confirmed" || item.status === "probable").length ?? 0;
  useEffect(() => {
    if (!activeCaseId) {
      setBacktest(null);
      return;
    }
    const controller = new AbortController();
    investigationApi.predictionBacktest(activeCaseId, controller.signal)
      .then(setBacktest)
      .catch((cause) => {
        if (!(cause instanceof DOMException && cause.name === "AbortError")) setBacktest(null);
      });
    return () => controller.abort();
  }, [activeCaseId, acceptedObservationCount]);

  useEffect(() => {
    if (!activeCaseId || !activeCaseStatus || ["completed", "cancelled"].includes(activeCaseStatus)) return;
    let disposed = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const refreshed = await investigationApi.workspace(activeCaseId);
        if (!disposed) {
          setWorkspace(refreshed);
          setCases((current) => current.map((item) => item.id === refreshed.case.id ? refreshed.case : item));
          setLastLiveUpdate(new Date());
        }
      } catch {
        // The last coherent workspace remains visible during a transient live-sync failure.
      } finally {
        if (!disposed) timer = window.setTimeout(poll, document.hidden ? 15_000 : 5_000);
      }
    };
    timer = window.setTimeout(poll, 5_000);
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [activeCaseId, activeCaseStatus]);

  const launch = async () => {
    setLaunching(true);
    setError(null);
    try {
      const created = await investigationApi.create({
        target_plate: plate,
        priority,
        reason,
        district: district || undefined,
      });
      setWorkspace(created);
      setCases((current) => [created.case, ...current.filter((item) => item.id !== created.case.id)]);
      setSelectedCandidateId(created.candidates[0]?.id ?? null);
      setLastLiveUpdate(new Date());
    } catch (cause) {
      setError(safeMessage(cause));
    } finally {
      setLaunching(false);
    }
  };

  const loadDemo = async () => {
    setDemoLoading(true);
    setError(null);
    try {
      const result = await investigationApi.seedDemo("GJ01AB1234");
      setPlate(result.target_plate);
      setDemoDisclosure(result.disclosure);
    } catch (cause) {
      setError(safeMessage(cause));
    } finally {
      setDemoLoading(false);
    }
  };

  const transition = async (status: "suspended" | "completed" | "active_tracking") => {
    if (!workspace) return;
    setLaunching(true);
    try {
      const updated = await investigationApi.transition(
        workspace.case.id,
        status,
        status === "suspended" ? "Investigator paused active tracking" : status === "completed" ? "Investigation objectives completed" : "Authorized tracking resumed",
      );
      setWorkspace(updated);
      setCases((current) => current.map((item) => item.id === updated.case.id ? updated.case : item));
    } catch (cause) {
      setError(safeMessage(cause));
    } finally {
      setLaunching(false);
    }
  };

  const selectedCandidate = workspace?.candidates.find((item) => item.id === selectedCandidateId) ?? workspace?.candidates[0];

  return (
    <div className="sie-page">
      <section className="sie-masthead">
        <div className="sie-masthead__identity">
          <span className="sie-orbit"><Crosshair size={24} /><i /><b /></span>
          <div><span className="panel-kicker">Restricted intelligence workspace</span><h1>Special Investigation Engine</h1><p>Cross-camera vehicle pursuit, evidence correlation and explainable route prediction.</p></div>
        </div>
        <div className="sie-live-posture"><span><i />Investigation event link</span><strong>{lastLiveUpdate ? `Synchronized ${relativeTime(lastLiveUpdate.toISOString())}` : "Establishing link"}</strong><small>Observation ≠ inference ≠ prediction</small></div>
      </section>

      {error ? <div className="sie-alert" role="alert"><ShieldAlert size={18} /><span><strong>Investigation operation did not complete</strong>{error}</span><button type="button" onClick={() => setError(null)}><X size={16} /></button></div> : null}

      <section className={`sie-launch${workspace ? " sie-launch--compact" : ""}`}>
        <div className="sie-launch__copy"><span><ScanSearch size={20} />Authorised target search</span><h2>{workspace ? "Open another investigation" : "Find the vehicle. Reconstruct the route. Focus the search."}</h2>{workspace ? null : <p>Enter a registration to search indexed ANPR observations, establish the last confirmed position and generate a bounded surveillance cone.</p>}</div>
        <div className="sie-launch__form">
          <label className="sie-plate-input"><small>Target vehicle registration</small><span><Target size={18} /><input aria-label="Target vehicle registration" value={plate} onChange={(event) => setPlate(event.target.value.toUpperCase())} maxLength={32} placeholder="GJ01AB1234" /></span></label>
          <label><small>Priority</small><select aria-label="Investigation priority" value={priority} onChange={(event) => setPriority(event.target.value as typeof priority)}><option value="critical">Critical pursuit</option><option value="high">High priority</option><option value="standard">Standard</option></select></label>
          <label><small>District scope</small><input aria-label="District scope" value={district} onChange={(event) => setDistrict(event.target.value)} placeholder="All districts" /></label>
          <label className="sie-reason"><small>Authorised purpose</small><input aria-label="Authorised purpose" value={reason} onChange={(event) => setReason(event.target.value)} /></label>
          <button className="button button--primary sie-launch-button" type="button" disabled={launching || plate.length < 6 || reason.length < 10} onClick={launch}>{launching ? <RefreshCw className="spin" size={17} /> : <Radar size={17} />}{launching ? "Correlating evidence…" : "Start investigation"}</button>
        </div>
        <footer><button type="button" onClick={loadDemo} disabled={demoLoading}><Sparkles size={15} />{demoLoading ? "Preparing disclosed scenario…" : "Load judge demonstration observations"}</button><span><ShieldCheck size={14} />Every search is actor-attributed and audit recorded</span></footer>
        {demoDisclosure ? <div className="sie-demo-disclosure"><AlertTriangle size={15} /><span><strong>Demonstration data loaded.</strong> {demoDisclosure} Start the investigation above to run it through the real correlation and prediction engine.</span></div> : null}
      </section>

      {workspace ? (
        <>
          <InvestigationCommandHeader workspace={workspace} onTransition={transition} busy={launching} />
          <div className="sie-command-grid">
            <CaseRail cases={cases} activeId={workspace.case.id} loading={loading} onOpen={(id) => void openCase(id)} />
            <section className="sie-map-panel">
              <header><div><span className="panel-kicker">Geospatial pursuit canvas</span><h2>Route intelligence</h2></div><div className="sie-map-legend"><span><i className="observed" />Observed</span><span><i className="inferred" />Inferred</span><span><i className="predicted" />Predicted</span></div></header>
              <InvestigationMap workspace={workspace} selectedCandidateId={selectedCandidate?.id ?? null} onSelectCandidate={setSelectedCandidateId} />
              <div className="sie-map-basis"><ShieldCheck size={15} /><span><small>Prediction basis</small><strong>{workspace.prediction_basis}</strong></span></div>
            </section>
            <PredictionPanel workspace={workspace} selected={selectedCandidate} onSelect={setSelectedCandidateId} />
          </div>
          <div className="sie-evidence-grid">
            <Timeline observations={workspace.observations} />
            <IntelligenceBrief workspace={workspace} selected={selectedCandidate} backtest={backtest} />
          </div>
          <VehicleReIDPanel
            investigationId={workspace.case.id}
            onConfirmed={() => void openCase(workspace.case.id)}
          />
        </>
      ) : loading ? <div className="sie-empty"><RefreshCw className="spin" size={26} /><strong>Opening restricted investigation console</strong></div> : (
        <div className="sie-empty"><Orbit size={34} /><strong>No active investigation selected</strong><p>Load the disclosed judge scenario or start an authorised target search.</p></div>
      )}
    </div>
  );
}

function InvestigationCommandHeader({ workspace, onTransition, busy }: { workspace: InvestigationWorkspace; onTransition: (status: "suspended" | "completed" | "active_tracking") => void; busy: boolean }) {
  const active = !["suspended", "completed", "cancelled"].includes(workspace.case.status);
  return <section className="sie-command-header">
    <div className="sie-case-seal"><span><Fingerprint size={20} /></span><div><small>{workspace.case.case_number}</small><strong>{workspace.case.target_plate}</strong><em>Target vehicle</em></div></div>
    <CommandMetric icon={Activity} label="Tracking state" value={titleCase(workspace.case.status)} tone="live" />
    <CommandMetric icon={LocateFixed} label="Last confirmed" value={workspace.last_confirmed_camera?.camera_code ?? "Not located"} detail={workspace.last_seen_at ? formatTimestamp(workspace.last_seen_at) : "Awaiting observation"} />
    <CommandMetric icon={Navigation} label="Movement" value={titleCase(workspace.movement_direction ?? "Establishing")} detail={`${workspace.observations.filter((item) => item.status !== "rejected").length} correlated sightings`} />
    <CommandMetric icon={Gauge} label="Route confidence" value={titleCase(workspace.case.route_confidence)} detail={`${workspace.candidates.length} candidate cameras`} />
    <div className="sie-case-actions"><button type="button" onClick={() => onTransition(active ? "suspended" : "active_tracking")} disabled={busy || workspace.case.status === "completed"}>{active ? <OctagonPause size={15} /> : <Play size={15} />}{active ? "Suspend" : "Resume"}</button><button type="button" onClick={() => onTransition("completed")} disabled={busy || workspace.case.status === "completed"}><CheckCircle2 size={15} />Complete</button></div>
  </section>;
}

function CommandMetric({ icon: Icon, label, value, detail, tone }: { icon: typeof Activity; label: string; value: string; detail?: string; tone?: string }) {
  return <div className={`sie-command-metric${tone ? ` sie-command-metric--${tone}` : ""}`}><Icon size={16} /><span><small>{label}</small><strong>{value}</strong>{detail ? <em>{detail}</em> : null}</span></div>;
}

function CaseRail({ cases, activeId, loading, onOpen }: { cases: InvestigationCase[]; activeId: string; loading: boolean; onOpen: (id: string) => void }) {
  return <aside className="sie-case-rail"><header><span><History size={16} />Case operations</span><b>{cases.length}</b></header><div>{cases.map((item) => <button key={item.id} type="button" className={item.id === activeId ? "active" : ""} onClick={() => onOpen(item.id)}><span className={`sie-case-priority sie-case-priority--${item.priority}`} /><div><strong>{item.target_plate}</strong><small>{item.case_number}</small><em>{titleCase(item.status)} · {relativeTime(item.updated_at)}</em></div><ChevronRight size={15} /></button>)}</div>{!cases.length && !loading ? <p>No investigation history.</p> : null}<footer><ShieldCheck size={14} />Case access attributed to demo-investigator</footer></aside>;
}

function PredictionPanel({ workspace, selected, onSelect }: { workspace: InvestigationWorkspace; selected?: InvestigationCandidate; onSelect: (id: string) => void }) {
  return <aside className="sie-prediction-panel"><header><div><span className="panel-kicker">Decision support</span><h2>Possible next cameras</h2></div><span className="sie-prediction-pulse"><i />LIVE</span></header><p className="sie-prediction-caution">Ranked candidates, not guaranteed destinations. Confidence decays until the next confirmed observation.</p><div className="sie-candidate-list">{workspace.candidates.slice(0, 8).map((item) => <button key={item.id} type="button" className={`${selected?.id === item.id ? "active " : ""}tier-${item.tier}`} onClick={() => onSelect(item.id)}><b>{String(item.rank).padStart(2, "0")}</b><span><strong>{item.camera.camera_code}</strong><small>{item.camera.camera_name}</small><em><TimerReset size={12} />ETA {eta(item)} · Tier {item.tier}</em></span><ConfidenceBadge value={item.confidence} /></button>)}</div>{selected ? <section className="sie-why"><span><Waypoints size={15} />Why {selected.camera.camera_code}?</span><ul>{selected.reasons.map((reason) => <li key={reason}><CheckCircle2 size={13} />{reason}</li>)}</ul><footer><code>{titleCase(selected.graph_method)}</code><small>{(selected.distance_m / 1000).toFixed(1)} km estimated separation</small></footer></section> : <div className="sie-no-candidates"><AlertTriangle size={20} />No defensible next-camera candidate is currently available.</div>}</aside>;
}

function ConfidenceBadge({ value }: { value: InvestigationConfidence }) {
  return <span className={`sie-confidence sie-confidence--${value}`}>{titleCase(value)}</span>;
}

function Timeline({ observations }: { observations: InvestigationObservation[] }) {
  return <section className="sie-timeline"><header><div><span className="panel-kicker">Evidence chronology</span><h2>Live target timeline</h2></div><span>{observations.length} observations</span></header><div>{observations.length ? observations.map((item, index) => { const Icon = statusIcon(item.status); return <article key={item.id} className={`sie-timeline-item sie-timeline-item--${item.status}`}><div className="sie-timeline-time"><strong>{new Date(item.event.observed_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</strong><small>{new Date(item.event.observed_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</small></div><span className="sie-timeline-node"><Icon size={15} />{index < observations.length - 1 ? <i /> : null}</span><div className="sie-timeline-detail"><header><span><strong>{item.camera.camera_code}</strong><small>{item.camera.camera_name}</small></span><b>{titleCase(item.status)}</b></header><div><span><small>OCR output</small><code>{item.event.plate_text}</code></span><span><small>Detection</small><strong>{Math.round(item.event.plate_confidence * 100)}%</strong></span><span><small>Correlation</small><strong>{Math.round(item.correlation_score * 100)}%</strong></span><span><small>Evidence</small><strong>Observed</strong></span></div><p>{item.reasoning.join(" · ")}</p></div></article>; }) : <div className="sie-timeline-empty"><FileSearch size={25} /><strong>Searching historical ANPR index</strong><p>No matching observation has crossed the controlled threshold.</p></div>}</div></section>;
}

function IntelligenceBrief({ workspace, selected, backtest }: { workspace: InvestigationWorkspace; selected?: InvestigationCandidate; backtest: PredictionBacktest | null }) {
  const metric = (value?: number | null) => value == null ? "N/A" : `${Math.round(value * 100)}%`;
  return <section className="sie-brief"><header><div><span className="panel-kicker">Investigator briefing</span><h2>Route intelligence</h2></div><Route size={19} /></header><div className="sie-brief-question"><small>Where was it?</small><strong>{workspace.last_confirmed_camera ? `${workspace.last_confirmed_camera.camera_name} · ${workspace.last_confirmed_camera.camera_code}` : "No confirmed location"}</strong></div><div className="sie-brief-question"><small>Where did it go?</small><strong>{workspace.movement_direction ? `${titleCase(workspace.movement_direction)} across ${workspace.route_segments.length} inferred connector${workspace.route_segments.length === 1 ? "" : "s"}` : "Direction not yet established"}</strong></div><div className="sie-brief-question"><small>Where should we look next?</small><strong>{selected ? `${selected.camera.camera_name} · ${titleCase(selected.confidence)} confidence · ${eta(selected)}` : "No defensible prediction"}</strong></div>{workspace.coverage_gaps.length ? <div className="sie-coverage-gap"><AlertTriangle size={17} /><span><strong>CCTV coverage gap</strong>{workspace.coverage_gaps.map((gap) => <small key={gap}>{gap}</small>)}</span></div> : null}<div className="sie-backtest"><header><span><Gauge size={14} />Prediction replay</span><small>{backtest?.evaluated_transitions ?? 0} route legs</small></header><div><span><small>Top 1</small><strong>{metric(backtest?.top_1_accuracy)}</strong></span><span><small>Top 3</small><strong>{metric(backtest?.top_3_accuracy)}</strong></span><span><small>Top 5</small><strong>{metric(backtest?.top_5_accuracy)}</strong></span></div><p>Retrospective engineering accuracy—not target-presence probability.</p></div><div className="sie-truth-model"><span><i className="observed" />Observation<strong>Evidence</strong></span><ArrowRight size={13} /><span><i className="inferred" />Correlation<strong>Inference</strong></span><ArrowRight size={13} /><span><i className="predicted" />Prediction<strong>Probability</strong></span></div><footer><Zap size={14} />Search locally first. Expand intelligently. Preserve statewide compute.</footer></section>;
}

function InvestigationMap({ workspace, selectedCandidateId, onSelectCandidate }: { workspace: InvestigationWorkspace; selectedCandidateId: string | null; onSelectCandidate: (id: string) => void }) {
  const accepted = workspace.observations.filter((item) => item.status === "confirmed" || item.status === "probable");
  const anchor = workspace.last_confirmed_camera;
  const points = [...accepted.map((item) => [item.camera.latitude, item.camera.longitude] as [number, number]), ...workspace.candidates.map((item) => [item.camera.latitude, item.camera.longitude] as [number, number])];
  return <div className="sie-map"><MapContainer center={GUJARAT_CENTER} zoom={8} minZoom={5} maxZoom={19} zoomControl attributionControl><TileLayer attribution={tileAttribution} url={tileUrl} maxZoom={19} />{workspace.route_segments.map((segment) => <Polyline key={`${segment.source_camera_id}-${segment.destination_camera_id}`} positions={segment.coordinates.map(([longitude, latitude]) => [latitude, longitude])} pathOptions={{ color: "#f2b84b", weight: 4, opacity: .86, dashArray: "10 8" }} />)}{anchor ? workspace.candidates.slice(0, 8).map((candidate) => <Polyline key={`prediction-${candidate.id}`} positions={[[anchor.latitude, anchor.longitude], [candidate.camera.latitude, candidate.camera.longitude]]} pathOptions={{ color: candidate.tier === 1 ? "#38d8cf" : "#4a96be", weight: candidate.tier === 1 ? 2.2 : 1.4, opacity: candidate.tier === 1 ? .62 : .34, dashArray: "3 9" }} />) : null}{accepted.map((item, index) => <Marker key={item.id} position={[item.camera.latitude, item.camera.longitude]} icon={observationIcon(index + 1, item.camera.id === workspace.case.latest_camera_id)}><Tooltip direction="top" offset={[0, -16]} opacity={1}><div className="sie-map-tooltip"><span>Observed detection</span><strong>{item.camera.camera_code}</strong><small>{item.camera.camera_name}</small><code>{item.event.plate_text} · {Math.round(item.correlation_score * 100)}% correlation</code></div></Tooltip></Marker>)}{workspace.candidates.map((item) => <CircleMarker key={item.id} center={[item.camera.latitude, item.camera.longitude]} radius={item.id === selectedCandidateId ? 15 : item.tier === 1 ? 11 : item.tier === 2 ? 9 : 7} pathOptions={{ color: item.tier === 1 ? "#42e0d7" : item.tier === 2 ? "#5ca6cf" : "#748a99", fillColor: item.id === selectedCandidateId ? "#42e0d7" : "#0b2835", fillOpacity: item.id === selectedCandidateId ? .42 : .18, weight: item.id === selectedCandidateId ? 4 : 2, dashArray: item.tier === 1 ? undefined : "4 4" }} eventHandlers={{ click: () => onSelectCandidate(item.id) }}><Tooltip direction="top" opacity={1}><div className="sie-map-tooltip"><span>Predicted · Tier {item.tier}</span><strong>{item.camera.camera_code}</strong><small>{item.camera.camera_name}</small><code>{titleCase(item.confidence)} confidence · ETA {eta(item)}</code></div></Tooltip></CircleMarker>)}{points.length ? <FitInvestigationBounds points={points} /> : null}</MapContainer><div className="sie-map-reticle"><Crosshair size={36} /><span>ACTIVE SEARCH CONE</span></div></div>;
}

function FitInvestigationBounds({ points }: { points: Array<[number, number]> }) {
  const map = useMap();
  const signature = points.map((item) => item.join(",")).join("|");
  useEffect(() => {
    const boundsPoints = signature.split("|").filter(Boolean).map((item) => item.split(",").map(Number) as [number, number]);
    if (boundsPoints.length === 1) map.setView(boundsPoints[0], 14);
    if (boundsPoints.length > 1) map.fitBounds(boundsPoints as LatLngBoundsExpression, { padding: [55, 55], maxZoom: 14 });
  }, [map, signature]);
  return null;
}

function observationIcon(sequence: number, latest: boolean) {
  return L.divIcon({
    className: "sie-observation-host",
    html: `<span class="sie-observation-marker${latest ? " latest" : ""}"><b>${sequence}</b><i></i></span>`,
    iconSize: latest ? [38, 38] : [30, 30],
    iconAnchor: latest ? [19, 19] : [15, 15],
  });
}
