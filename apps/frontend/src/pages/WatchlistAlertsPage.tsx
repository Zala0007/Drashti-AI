import {
  AlertTriangle,
  BadgeCheck,
  BellRing,
  Camera,
  CheckCircle2,
  Clock3,
  Eye,
  FileCheck2,
  Plus,
  RadioTower,
  ScanLine,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiError, apiMediaUrl, watchlistApi } from "../lib/api";
import type { WatchlistAlert, WatchlistDashboard, WatchlistEntry } from "../types/watchlist";

const emptyDashboard: WatchlistDashboard = {
  active_entries: 0,
  total_entries: 0,
  new_alerts: 0,
  latest_alert_at: null,
};

const observedTime = (value: string) => new Date(value).toLocaleString("en-IN", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function WatchlistAlertsPage() {
  const [dashboard, setDashboard] = useState(emptyDashboard);
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [alerts, setAlerts] = useState<WatchlistAlert[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [plate, setPlate] = useState("");
  const [label, setLabel] = useState("Evaluation target vehicle");
  const [reason, setReason] = useState("Technical evaluation live watch");
  const [severity, setSeverity] = useState<"critical" | "high" | "standard">("critical");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextDashboard, nextEntries, nextAlerts] = await Promise.all([
        watchlistApi.dashboard(signal),
        watchlistApi.entries(signal),
        watchlistApi.alerts(signal),
      ]);
      setDashboard(nextDashboard);
      setEntries(nextEntries.items);
      setAlerts(nextAlerts.items);
      setSelectedId((current) => current ?? nextAlerts.items[0]?.id ?? null);
      setError(null);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(cause instanceof ApiError ? cause.message : "Watchlist service is unavailable.");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh(controller.signal);
    }, 4000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [refresh]);

  const selected = useMemo(
    () => alerts.find((item) => item.id === selectedId) ?? alerts[0] ?? null,
    [alerts, selectedId],
  );

  const createEntry = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await watchlistApi.createEntry({
        plate_text: plate,
        subject_label: label,
        reason,
        severity,
      });
      setPlate("");
      await refresh();
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Watchlist entry could not be created.",
      );
    } finally {
      setBusy(false);
    }
  };

  const acknowledge = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await watchlistApi.reviewAlert(selected.id, "acknowledged");
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return <div className="watchlist-page">
    <section className="watchlist-masthead">
      <div className="watchlist-masthead__identity">
        <span className="watchlist-signal"><BellRing size={25} /><i /><b /></span>
        <div><span className="panel-kicker">P-S05 | Continuous ANPR cross-reference</span><h1>Watchlist Alert Command</h1><p>Live hybrid-OCR matches, camera evidence and accountable response workflow.</p></div>
      </div>
      <aside><span><i />Matching engine active</span><strong>{dashboard.new_alerts} new alert{dashboard.new_alerts === 1 ? "" : "s"}</strong><small>{dashboard.active_entries} active / {dashboard.total_entries} total watch entries</small></aside>
    </section>

    <div className="watchlist-disclosure"><ShieldCheck size={16} /><span><strong>Controlled operational aid.</strong> Only accepted hybrid OCR results enter exact watchlist matching. Provider conflicts remain quarantined for officer review and never generate an alert.</span></div>
    {error ? <div className="watchlist-disclosure"><AlertTriangle size={16} />{error}</div> : null}

    <section className="watchlist-entry-console">
      <form onSubmit={createEntry}>
        <header><Plus size={17} /><div><strong>Add evaluation watch</strong><small>The registration becomes active immediately.</small></div></header>
        <input required minLength={5} maxLength={32} value={plate} onChange={(event) => setPlate(event.target.value.toUpperCase())} placeholder="Registration number" />
        <input required minLength={3} value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Target label" />
        <input required minLength={5} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Authorized reason" />
        <select value={severity} onChange={(event) => setSeverity(event.target.value as typeof severity)}><option value="critical">Critical</option><option value="high">High</option><option value="standard">Standard</option></select>
        <button disabled={busy} type="submit"><Plus size={15} />{busy ? "Saving..." : "Add to watchlist"}</button>
      </form>
      <div className="watchlist-entry-register">
        <header><ShieldCheck size={17} /><strong>Active watch register</strong><span>{entries.length} records</span></header>
        {entries.length ? entries.map((entry) => <article key={entry.id}><span className={`watchlist-entry-register__severity watchlist-entry-register__severity--${entry.severity}`}>{entry.severity}</span><div><strong>{entry.normalized_plate}</strong><small>{entry.subject_label} | {entry.reason}</small></div><button type="button" onClick={() => void watchlistApi.updateEntry(entry.id, entry.status === "active" ? "inactive" : "active").then(() => refresh())}>{entry.status}</button></article>) : <p>No watch entries yet. Add the evaluation registration above.</p>}
      </div>
    </section>

    {selected ? <AlertCommand selected={selected} busy={busy} onAcknowledge={acknowledge} /> : <section className="watchlist-command watchlist-command--empty"><BellRing size={34} /><h2>No live match received</h2><p>The engine is polling all accepted ANPR events against {dashboard.active_entries} active entries.</p></section>}

    <div className="watchlist-intelligence">
      <section className="watchlist-trace"><header><div><span className="panel-kicker">Real alert stream</span><h2>Latest matched sightings</h2></div><span><i />{alerts.length} retained events</span></header><div className="watchlist-alert-list">{alerts.map((alert) => <button type="button" key={alert.id} className={selected?.id === alert.id ? "active" : ""} onClick={() => setSelectedId(alert.id)}><Camera size={15} /><span><strong>{alert.matched_plate}</strong><small>{alert.camera_code} | {alert.camera_name}</small></span><time>{observedTime(alert.observed_at)}</time><em>{alert.status}</em></button>)}</div></section>
      <section className="watchlist-audit"><header><div><span className="panel-kicker">Governed response</span><h2>Automated control state</h2></div><Clock3 size={18} /></header><ol><li className="done"><i /><span><strong>Hybrid OCR accepted</strong><small>Unresolved provider conflicts excluded</small></span></li><li className="done"><i /><span><strong>Watchlist evaluated</strong><small>Exact normalized active-rule match</small></span></li><li className={selected?.status === "new" ? "current" : "done"}><i /><span><strong>Officer review</strong><small>{selected?.status ?? "Awaiting a live alert"}</small></span></li><li className={selected && selected.status !== "new" ? "done" : ""}><i /><span><strong>Disposition retained</strong><small>Actor and timestamp preserved in audit</small></span></li></ol></section>
    </div>
  </div>;
}

function AlertCommand({ selected, busy, onAcknowledge }: {
  selected: WatchlistAlert;
  busy: boolean;
  onAcknowledge: () => Promise<void>;
}) {
  return <section className="watchlist-command">
    <header><div><span className="watchlist-priority"><AlertTriangle size={15} />{selected.entry.severity} match</span><small>Alert ID | {selected.id.slice(0, 12).toUpperCase()}</small></div><div className="watchlist-clock"><i /><span><small>Observed</small><strong>{observedTime(selected.observed_at)}</strong></span></div></header>
    <div className="watchlist-command__body">
      <article className="watchlist-capture">
        <div className="watchlist-capture__image">{selected.evidence_reference ? <img src={apiMediaUrl(selected.evidence_reference)} alt={`Hybrid OCR evidence for ${selected.matched_plate}`} /> : <ScanLine size={42} />}<span><ScanLine size={14} />Hybrid OCR evidence</span><i /><b /></div>
        <div className="watchlist-capture__identity"><small>Normalized registration</small><strong>{selected.matched_plate}</strong><span><BadgeCheck size={15} />Accepted OCR | {Math.round(selected.ocr_confidence * 100)}%</span></div>
        <dl><div><dt>Target</dt><dd>{selected.entry.subject_label}</dd></div><div><dt>Rule</dt><dd>{selected.entry.reason}</dd></div><div><dt>Camera</dt><dd>{selected.camera_code}</dd></div><div><dt>Location</dt><dd>{selected.camera_name} | {selected.district}</dd></div></dl>
      </article>
      <article className="watchlist-assessment"><header><span><Eye size={17} />Correlation assessment</span><b>{selected.entry.severity.toUpperCase()}</b></header><div className="watchlist-score"><span><strong>{Math.round(selected.match_score * 100)}</strong><small>/100</small></span><div><i style={{ width: `${selected.match_score * 100}%` }} /><small>Exact normalized match</small></div></div><ul><li><CheckCircle2 />Active authorized watch entry</li><li><CheckCircle2 />Exact normalized registration match</li><li><CheckCircle2 />Camera and timestamp retained</li><li><CheckCircle2 />Original plate crop linked for review</li></ul><footer><ShieldCheck size={15} />Machine correlates; an authorized officer decides.</footer></article>
      <aside className="watchlist-actions"><header><RadioTower size={18} /><span><small>Response posture</small><strong>{selected.status === "new" ? "Awaiting disposition" : selected.status}</strong></span></header><button disabled={busy || selected.status !== "new"} type="button" className="primary" onClick={() => void onAcknowledge()}><Eye size={16} />Acknowledge alert</button><button type="button" onClick={() => { window.location.hash = "#/investigation"; }}><FileCheck2 size={16} />Open investigation</button><div><ShieldCheck size={15} /><span><small>Alert source</small><strong>Live hybrid ANPR</strong></span></div></aside>
    </div>
  </section>;
}
