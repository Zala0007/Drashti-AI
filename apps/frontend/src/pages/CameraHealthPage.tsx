import {
  Activity,
  AlertOctagon,
  Camera,
  CheckCircle2,
  Clock3,
  Gauge,
  HeartPulse,
  LoaderCircle,
  RadioTower,
  ShieldCheck,
  Signal,
  TriangleAlert,
  Wrench,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { advancedApi, ApiError } from "../lib/api";
import { formatTimestamp, titleCase } from "../lib/format";
import type { HealthAggregate, HealthDashboard, HealthHistory } from "../types/advanced";

export function CameraHealthPage() {
  const [dashboard, setDashboard] = useState<HealthDashboard | null>(null);
  const [history, setHistory] = useState<HealthHistory | null>(null);
  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    const next = await advancedApi.health(signal);
    setDashboard(next);
    const selected = selectedCameraId ?? next.latest[0]?.camera.id;
    if (selected) {
      setSelectedCameraId(selected);
      setHistory(await advancedApi.healthHistory(selected, signal));
    }
  }, [selectedCameraId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    load(controller.signal)
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof ApiError ? cause.message : "Health telemetry is unavailable.");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [load]);

  const select = async (cameraId: string) => {
    setSelectedCameraId(cameraId);
    try { setHistory(await advancedApi.healthHistory(cameraId)); }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : "Camera history is unavailable."); }
  };

  const capture = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await advancedApi.captureHealth();
      setDashboard(next);
      if (selectedCameraId) setHistory(await advancedApi.healthHistory(selectedCameraId));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Live snapshot failed.");
    } finally { setBusy(false); }
  };

  const states = dashboard?.states ?? {};
  const operational = (states.healthy ?? 0) + (states.degraded ?? 0);
  return <div className="advanced-page health-page">
    <section className="advanced-masthead health-masthead">
      <div><span className="advanced-emblem"><HeartPulse size={25} /><i /></span><span><small>P-S03 · Operational resilience</small><h1>Camera Health & Maintenance</h1><p>Measured stream posture, incident grouping and explainable maintenance trends.</p></span></div>
      <button className="button button--primary" type="button" disabled={busy} onClick={() => void capture()}>{busy ? <LoaderCircle className="spin" size={16} /> : <RadioTower size={16} />}Capture live telemetry</button>
    </section>
    {error ? <div className="advanced-alert"><TriangleAlert size={16} />{error}<button type="button" onClick={() => setError(null)}><X size={14} /></button></div> : null}
    <section className="health-kpis">
      <HealthKpi icon={Camera} label="Registered nodes" value={dashboard?.total_cameras ?? 0} detail="Registry scope" tone="neutral" />
      <HealthKpi icon={CheckCircle2} label="Operational" value={operational} detail="Healthy + degraded" tone="healthy" />
      <HealthKpi icon={AlertOctagon} label="Critical / offline" value={(states.critical ?? 0) + (states.offline ?? 0)} detail="Needs attention" tone="critical" />
      <HealthKpi icon={Wrench} label="Maintenance risk" value={(dashboard?.maintenance_risk.high ?? 0) + (dashboard?.maintenance_risk.medium ?? 0)} detail="Rule-based findings" tone="warning" />
      <HealthKpi icon={Activity} label="Open incidents" value={dashboard?.incidents.length ?? 0} detail="Debounced + grouped" tone="signal" />
    </section>
    <div className="health-layout">
      <section className="health-fleet">
        <header><div><span className="panel-kicker">Statewide fleet matrix</span><h2>Camera telemetry</h2></div><span><i />Persisted aggregates</span></header>
        <div className="health-fleet__table"><div className="health-fleet__head"><span>Camera</span><span>State</span><span>Decode</span><span>Latency</span><span>Availability</span><span>Source</span></div>{dashboard?.latest.map((item) => <button key={item.id} type="button" className={selectedCameraId === item.camera.id ? "active" : ""} onClick={() => void select(item.camera.id)}><span><i className={`health-dot health-dot--${item.health_state}`} /><b>{item.camera.camera_code}</b><small>{item.camera.camera_name}</small></span><span><em className={`advanced-tone advanced-tone--${item.health_state}`}>{titleCase(item.health_state)}</em></span><span>{item.decoded_fps == null ? "—" : `${item.decoded_fps.toFixed(1)} fps`}</span><span>{item.latency_ms == null ? "—" : `${Math.round(item.latency_ms)} ms`}</span><span>{Math.round(item.availability * 100)}%</span><span>{titleCase(item.source)}</span></button>)}</div>
        {loading ? <div className="advanced-loading"><LoaderCircle className="spin" size={19} />Loading measured fleet posture…</div> : !dashboard?.latest.length ? <div className="advanced-empty"><Signal size={26} /><strong>No aggregate telemetry yet</strong><p>Capture a live snapshot to persist stream-engine or registry-heartbeat measurements.</p></div> : null}
      </section>
      <aside className="health-inspector">
        <header><div><span className="panel-kicker">Diagnostic trace</span><h2>{history?.camera.camera_code ?? "Select camera"}</h2><p>{history?.camera.camera_name ?? "Open a fleet row to inspect real aggregate history."}</p></div><Gauge size={20} /></header>
        {history?.items.length ? <><HealthSparkline items={history.items} /><div className="health-now"><Diagnostic label="Latest state" value={titleCase(history.items[0].health_state)} /><Diagnostic label="Frame age" value={history.items[0].frame_age_ms == null ? "Not measured" : `${Math.round(history.items[0].frame_age_ms)} ms`} /><Diagnostic label="Reconnects" value={String(history.items[0].reconnect_count)} /><Diagnostic label="AI worker" value={titleCase(history.items[0].ai_worker_state)} /></div><div className="health-history"><h3><Clock3 size={15} />Aggregate history</h3>{history.items.slice(0, 8).map((item) => <div key={item.id}><i className={`health-dot health-dot--${item.health_state}`} /><span><strong>{titleCase(item.health_state)}</strong><small>{formatTimestamp(item.bucket_start)}</small></span><em>{Math.round(item.availability * 100)}%</em></div>)}</div><footer><ShieldCheck size={13} />{history.telemetry_basis}</footer></> : <div className="advanced-empty"><Gauge size={25} /><strong>No history for this camera</strong></div>}
      </aside>
    </div>
    <div className="health-intelligence-grid">
      <section className="incident-board"><header><div><span className="panel-kicker">Incident suppression</span><h2>Actionable incidents</h2></div><b>{dashboard?.incidents.length ?? 0}</b></header>{dashboard?.incidents.map((item) => <article key={item.id}><AlertOctagon size={18} /><span><strong>{item.title}</strong><p>{item.explanation}</p><small>{item.affected_camera_ids.length} affected cameras · {item.edge_node_id ?? "Individual node"}</small></span><em>{item.severity}</em></article>)}{!dashboard?.incidents.length ? <div className="advanced-empty compact"><CheckCircle2 size={23} /><strong>No persistent incidents open</strong><p>Transient samples remain suppressed until the debounce condition is met.</p></div> : null}</section>
      <section className="maintenance-board"><header><div><span className="panel-kicker">Explainable maintenance</span><h2>Trend findings</h2></div><Wrench size={18} /></header>{dashboard?.findings.map((item) => <article key={item.id}><span><strong>{item.camera.camera_code}</strong><small>{item.camera.camera_name}</small></span><em className={`advanced-tone advanced-tone--${item.risk}`}>{item.risk}</em><ul>{item.indicators.map((indicator) => <li key={indicator}>{indicator}</li>)}</ul><p>{item.explanation}</p></article>)}{!dashboard?.findings.length ? <div className="advanced-empty compact"><Wrench size={22} /><strong>No maintenance trend crossed a rule threshold</strong></div> : null}</section>
    </div>
    <div className="advanced-disclosure"><ShieldCheck size={15} />{dashboard?.telemetry_basis ?? "Health states appear only after measured or registry telemetry is available."}</div>
  </div>;
}

function HealthKpi({ icon: Icon, label, value, detail, tone }: { icon: typeof Camera; label: string; value: number; detail: string; tone: string }) { return <div className={`health-kpi health-kpi--${tone}`}><Icon size={18} /><span><small>{label}</small><strong>{value.toLocaleString("en-IN")}</strong><em>{detail}</em></span></div>; }
function Diagnostic({ label, value }: { label: string; value: string }) { return <span><small>{label}</small><strong>{value}</strong></span>; }
function HealthSparkline({ items }: { items: HealthAggregate[] }) {
  const values = useMemo(() => [...items].reverse().slice(-24).map((item) => item.availability), [items]);
  const points = values.map((value, index) => `${values.length === 1 ? 50 : index / (values.length - 1) * 100},${38 - value * 32}`).join(" ");
  return <div className="health-sparkline"><header><span><Signal size={14} />Availability trace</span><strong>{Math.round((values.at(-1) ?? 0) * 100)}%</strong></header><svg viewBox="0 0 100 42" preserveAspectRatio="none" aria-label="Availability history"><defs><linearGradient id="healthArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#42e0d7" stopOpacity=".35"/><stop offset="1" stopColor="#42e0d7" stopOpacity="0"/></linearGradient></defs><polyline points={`0,42 ${points} 100,42`} fill="url(#healthArea)" stroke="none"/><polyline points={points} fill="none" stroke="#42e0d7" strokeWidth="1.8" vectorEffect="non-scaling-stroke"/></svg></div>;
}
