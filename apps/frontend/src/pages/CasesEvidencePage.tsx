import {
  Archive,
  BadgeCheck,
  BriefcaseBusiness,
  Clock3,
  Download,
  FileCheck2,
  FileKey2,
  Fingerprint,
  Link2,
  LoaderCircle,
  LockKeyhole,
  Plus,
  Route,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { advancedApi, ApiError, investigationApi } from "../lib/api";
import { formatTimestamp, relativeTime, titleCase } from "../lib/format";
import type { CaseFile, CaseWorkspace } from "../types/advanced";
import type { InvestigationCase } from "../types/investigation";

export function CasesEvidencePage() {
  const [cases, setCases] = useState<CaseFile[]>([]);
  const [workspace, setWorkspace] = useState<CaseWorkspace | null>(null);
  const [investigations, setInvestigations] = useState<InvestigationCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("Authorized vehicle intelligence case");
  const [description, setDescription] = useState("Controlled case workspace for reviewed cross-camera vehicle intelligence.");
  const [authorization, setAuthorization] = useState("AUTH-DEMO-2026-001");
  const [investigationId, setInvestigationId] = useState("");
  const [exportNote, setExportNote] = useState<string | null>(null);

  const open = useCallback(async (id: string, signal?: AbortSignal) => {
    const detail = await advancedApi.caseWorkspace(id, signal);
    setWorkspace(detail);
  }, []);

  const load = useCallback(async (signal?: AbortSignal) => {
    const [caseList, investigationList] = await Promise.all([
      advancedApi.cases(signal),
      investigationApi.list(signal),
    ]);
    setCases(caseList.items);
    setInvestigations(investigationList.items);
    if (caseList.items[0]) await open(caseList.items[0].id, signal);
  }, [open]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    load(controller.signal)
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof ApiError ? cause.message : "Case workspace is unavailable.");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [load]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return term ? cases.filter((item) => `${item.case_number} ${item.title}`.toLowerCase().includes(term)) : cases;
  }, [cases, search]);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await advancedApi.createCase({
        title,
        description,
        priority: "high",
        authorization_reference: authorization,
        investigation_id: investigationId || undefined,
      });
      setWorkspace(created);
      setCases((current) => [created.case, ...current]);
      setShowCreate(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The case could not be opened.");
    } finally {
      setBusy(false);
    }
  };

  const exportCase = async () => {
    if (!workspace) return;
    setBusy(true);
    try {
      const result = await advancedApi.exportCase(workspace.case.id);
      setWorkspace(result.workspace);
      setExportNote(result.integrity_disclosure);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Case export failed.");
    } finally {
      setBusy(false);
    }
  };

  return <div className="advanced-page case-page">
    <section className="advanced-masthead">
      <div><span className="advanced-emblem"><BriefcaseBusiness size={25} /><i /></span><span><small>P-S02 · Restricted workspace</small><h1>Case & Evidence Management</h1><p>Investigation records, controlled evidence references and immutable activity context.</p></span></div>
      <aside><LockKeyhole size={17} /><span><small>Access posture</small><strong>Assigned investigator · audited actions</strong></span></aside>
    </section>
    {error ? <div className="advanced-alert" role="alert"><FileKey2 size={16} />{error}</div> : null}
    {exportNote ? <div className="advanced-disclosure"><ShieldCheck size={15} />{exportNote}</div> : null}
    <section className="case-toolbar">
      <label><Search size={16} /><input aria-label="Search cases" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search case number or title" /></label>
      <span><b>{cases.length}</b> controlled cases</span>
      <button className="button button--primary" type="button" onClick={() => setShowCreate((value) => !value)}><Plus size={16} />Open case</button>
    </section>
    {showCreate ? <section className="case-create advanced-enter"><header><div><small>New controlled record</small><h2>Open an investigation case</h2></div><Fingerprint size={23} /></header><div><label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} /></label><label>Authorization reference<input value={authorization} onChange={(event) => setAuthorization(event.target.value)} /></label><label>Link investigation<select value={investigationId} onChange={(event) => setInvestigationId(event.target.value)}><option value="">No linked investigation</option>{investigations.map((item) => <option key={item.id} value={item.id}>{item.case_number} · {item.target_plate}</option>)}</select></label><label className="wide">Purpose and context<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label></div><footer><span><ShieldCheck size={14} />Authorization is retained with the case record.</span><button className="button button--primary" type="button" disabled={busy || title.length < 5 || description.length < 10 || authorization.length < 5} onClick={() => void create()}>{busy ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}Create controlled case</button></footer></section> : null}
    <div className="case-layout">
      <aside className="case-rail"><header><span><Archive size={16} />Case register</span><b>{filtered.length}</b></header><div>{filtered.map((item) => <button key={item.id} type="button" className={workspace?.case.id === item.id ? "active" : ""} onClick={() => void open(item.id)}><i className={`priority priority--${item.priority}`} /><span><strong>{item.case_number}</strong><small>{item.title}</small><em>{titleCase(item.status)} · {relativeTime(item.updated_at)}</em></span></button>)}</div>{loading ? <p><LoaderCircle className="spin" size={18} />Opening case register…</p> : !filtered.length ? <p>No controlled cases match this view.</p> : null}</aside>
      <main className="case-workspace">
        {workspace ? <>
          <header className="case-workspace__header"><div><span className="panel-kicker">{workspace.case.case_number}</span><h2>{workspace.case.title}</h2><p>{workspace.case.description}</p></div><div><span className={`advanced-tone advanced-tone--${workspace.case.priority}`}>{workspace.case.priority}</span><button type="button" disabled={busy} onClick={() => void exportCase()}><Download size={15} />Structured export</button></div></header>
          <div className="case-metrics"><Metric icon={FileCheck2} label="Evidence records" value={workspace.evidence.length} detail="Controlled metadata" /><Metric icon={BadgeCheck} label="Integrity manifests" value={workspace.integrity_verified} detail="SHA-256 captured" /><Metric icon={Route} label="Route cameras" value={workspace.route_camera_sequence.length} detail={workspace.target_plate ?? "No target linked"} /><Metric icon={Clock3} label="Activity events" value={workspace.activity.length} detail="Actor attributed" /></div>
          <div className="case-content-grid">
            <section className="evidence-ledger"><header><div><span className="panel-kicker">Evidence ledger</span><h3>Controlled records</h3></div><LockKeyhole size={17} /></header><div>{workspace.evidence.map((item) => <article key={item.id}><span className="evidence-ledger__icon"><FileCheck2 size={18} /></span><div><header><strong>{titleCase(item.evidence_type)}</strong><b>{titleCase(item.classification)}</b></header><p>{item.camera ? `${item.camera.camera_code} · ${item.camera.camera_name}` : titleCase(item.source_type)}</p><footer><span>{formatTimestamp(item.occurred_at)}</span><code>{item.sha256 ? `${item.sha256.slice(0, 12)}…${item.sha256.slice(-8)}` : "Integrity unavailable"}</code></footer></div></article>)}</div>{!workspace.evidence.length ? <div className="advanced-empty"><Link2 size={25} /><strong>No evidence attached</strong><p>Link an authorized investigation to import accepted observations.</p></div> : null}</section>
            <section className="activity-ledger"><header><div><span className="panel-kicker">Audit context</span><h3>Activity stream</h3></div></header><div>{workspace.activity.map((item) => <article key={item.id}><i /><span><strong>{item.summary}</strong><small>{item.actor_id} · {formatTimestamp(item.created_at)}</small><em>{titleCase(item.action)}</em></span></article>)}</div></section>
          </div>
        </> : <div className="advanced-empty"><BriefcaseBusiness size={34} /><strong>Select or open a controlled case</strong><p>Case evidence is never generated without an authorized source record.</p></div>}
      </main>
    </div>
  </div>;
}

function Metric({ icon: Icon, label, value, detail }: { icon: typeof FileCheck2; label: string; value: number; detail: string }) {
  return <div><Icon size={17} /><span><small>{label}</small><strong>{value.toLocaleString("en-IN")}</strong><em>{detail}</em></span></div>;
}
