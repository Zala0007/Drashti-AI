import {
  Aperture,
  ArrowRight,
  BadgeCheck,
  BrainCircuit,
  Bus,
  CalendarClock,
  CarFront,
  ChevronLeft,
  ChevronRight,
  CircleGauge,
  CloudCog,
  Database,
  Eye,
  Fingerprint,
  Focus,
  ImageOff,
  Layers3,
  Maximize2,
  Network,
  ScanEye,
  ScanLine,
  Search,
  ShieldCheck,
  Truck,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useState, type CSSProperties } from "react";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { aiApi, apiMediaUrl, ApiError } from "../lib/api";
import type {
  AIDetection,
  AIFeatureStatus,
  AIPage,
  AIPlateDetection,
  AIShowcaseOverview,
} from "../types/ai";

const vehicleClasses = ["all", "car", "truck", "bus", "motorcycle"] as const;
const emptyPage = <T,>(): AIPage<T> => ({ items: [], total: 0, page: 1, page_size: 0, pages: 1 });
const featureIcons: Record<string, LucideIcon> = {
  vehicle_detection: Focus,
  vehicle_tracking: Network,
  vehicle_database: Database,
  plate_detection: ScanLine,
  cloud_ocr: CloudCog,
  temporal_consensus: Layers3,
  investigation_handoff: ShieldCheck,
  vehicle_reid: Fingerprint,
  visual_intelligence: ScanEye,
};

const percentage = (value: number | null) => value == null ? "—" : `${Math.round(value * 100)}%`;
const titleCase = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const evidenceTime = (value: string) => {
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized) ? normalized : `${normalized}Z`;
  const date = new Date(zoned);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};

export function AIIntelligencePage() {
  const [overview, setOverview] = useState<AIShowcaseOverview | null>(null);
  const [detections, setDetections] = useState<AIPage<AIDetection>>(emptyPage);
  const [plates, setPlates] = useState<AIPage<AIPlateDetection>>(emptyPage);
  const [query, setQuery] = useState("");
  const [plateQuery, setPlateQuery] = useState("");
  const [vehicleClass, setVehicleClass] = useState<(typeof vehicleClasses)[number]>("all");
  const [minimumConfidence, setMinimumConfidence] = useState(0.55);
  const [detectionPage, setDetectionPage] = useState(1);
  const [platePage, setPlatePage] = useState(1);
  const [selected, setSelected] = useState<AIDetection | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [loadingDetections, setLoadingDetections] = useState(true);
  const [loadingPlates, setLoadingPlates] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(query, 260);
  const debouncedPlateQuery = useDebouncedValue(plateQuery, 260);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingOverview(true);
    aiApi.overview(controller.signal)
      .then(setOverview)
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof ApiError ? cause.message : "AI evidence overview is unavailable.");
      })
      .finally(() => setLoadingOverview(false));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingDetections(true);
    aiApi.detections({
      query: debouncedQuery,
      className: vehicleClass === "all" ? undefined : vehicleClass,
      minimumConfidence,
      page: detectionPage,
      pageSize: 12,
    }, controller.signal)
      .then(setDetections)
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof ApiError ? cause.message : "Vehicle evidence could not be loaded.");
      })
      .finally(() => setLoadingDetections(false));
    return () => controller.abort();
  }, [debouncedQuery, detectionPage, minimumConfidence, vehicleClass]);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingPlates(true);
    aiApi.plates({ query: debouncedPlateQuery, page: platePage, pageSize: 10 }, controller.signal)
      .then(setPlates)
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof ApiError ? cause.message : "Plate intelligence could not be loaded.");
      })
      .finally(() => setLoadingPlates(false));
    return () => controller.abort();
  }, [debouncedPlateQuery, platePage]);

  useEffect(() => {
    const controller = new AbortController();
    const refreshLiveEvidence = () => {
      if (document.visibilityState !== "visible") return;
      void aiApi.overview(controller.signal).then(setOverview).catch(() => undefined);
      void aiApi.detections({
        query: debouncedQuery,
        className: vehicleClass === "all" ? undefined : vehicleClass,
        minimumConfidence,
        page: detectionPage,
        pageSize: 12,
      }, controller.signal).then(setDetections).catch(() => undefined);
      void aiApi.plates({
        query: debouncedPlateQuery,
        page: platePage,
        pageSize: 10,
      }, controller.signal).then(setPlates).catch(() => undefined);
    };
    const timer = window.setInterval(refreshLiveEvidence, 6000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [debouncedPlateQuery, debouncedQuery, detectionPage, minimumConfidence, platePage, vehicleClass]);

  const selectClass = (value: (typeof vehicleClasses)[number]) => {
    setVehicleClass(value);
    setDetectionPage(1);
  };

  return <div className="ai-studio">
    <section className="ai-hero">
      <div className="ai-hero__copy">
        <span className="ai-hero__eyebrow"><ShieldCheck size={14} /> Directorate video analytics · Evidence review</span>
        <h1>Video Analytics &amp;<br /><em>Evidence Review</em></h1>
        <p>Review vehicle detections, track records, number-plate crops and OCR output produced by the configured analytics services. All results remain subject to authorized verification.</p>
        <div className="ai-hero__signals">
          <span><i className={overview?.available ? "online" : "pending"} />{overview?.available ? "Evidence archive online" : "Evidence archive pending"}</span>
          <span><BadgeCheck size={14} />Model version recorded</span>
          <span><ShieldCheck size={14} />Officer review required</span>
        </div>
      </div>
      <aside className="ai-hero__register" aria-label="Current evidence register">
        <header><Database size={18} /><span><small>Current evidence register</small><strong>{overview?.available ? "AVAILABLE" : "NOT AVAILABLE"}</strong></span></header>
        <dl><div><dt>Vehicle records</dt><dd>{overview?.vehicle_detections.toLocaleString("en-IN") ?? "—"}</dd></div><div><dt>Plate crops</dt><dd>{overview?.plate_detections.toLocaleString("en-IN") ?? "—"}</dd></div><div><dt>Accepted OCR</dt><dd>{overview?.readable_plate_detections.toLocaleString("en-IN") ?? "—"}</dd></div><div><dt>Visual profiles</dt><dd>{(overview?.visual_profiles ?? 0).toLocaleString("en-IN")}</dd></div></dl>
        <footer><ShieldCheck size={14} />Read-only evidence projection</footer>
      </aside>
    </section>

    {error ? <div className="ai-alert"><ImageOff size={17} /><span><strong>Evidence service notice</strong>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Dismiss notice"><X size={16} /></button></div> : null}

    <section className="ai-kpis" aria-label="Observed AI evidence metrics">
      <Metric icon={CarFront} label="Vehicle evidence" value={overview?.vehicle_detections} note="searchable stored crops" loading={loadingOverview} />
      <Metric icon={ScanLine} label="Plate crops" value={overview?.plate_detections} note={`${overview?.readable_plate_detections ?? 0} normalized OCR readings`} loading={loadingOverview} tone="violet" />
      <Metric icon={Fingerprint} label="Unique tracks" value={overview?.unique_tracks} note="source-track identities" loading={loadingOverview} tone="amber" />
      <Metric icon={CircleGauge} label="Observed confidence" value={percentage(overview?.average_confidence ?? null)} note="not benchmark accuracy" loading={loadingOverview} tone="green" />
      <Metric icon={Aperture} label="Frames indexed" value={overview?.frame_count} note={`${overview?.source_count ?? 0} evidence source`} loading={loadingOverview} tone="blue" />
      <Metric icon={ScanEye} label="Visual profiles" value={overview?.visual_profiles} note={`${overview?.visual_pending ?? 0} awaiting Groq enrichment`} loading={loadingOverview} tone="steel" />
    </section>

    <section className="ai-model-ledger">
      <header><div><span className="ai-kicker">Active inference register</span><h2>Every configured model and its linked output</h2></div><ShieldCheck size={21} /></header>
      <div>{(overview?.models ?? []).map((model) => <article key={model.key}><header><code>{model.model_id ?? model.key.toUpperCase()}</code><span className={`ai-model-ledger__status ai-model-ledger__status--${model.status.includes("pending") ? "pending" : "ready"}`}><i />{titleCase(model.status)}</span></header><h3>{model.name}</h3><p>{model.purpose}</p><small>{model.detail}</small><footer><strong>{(model.output_count ?? 0).toLocaleString("en-IN")}</strong> linked outputs</footer></article>)}</div>
    </section>

    <section className="ai-pipeline-panel">
      <header><div><span className="ai-kicker">Processing sequence</span><h2>Analytics and review workflow</h2></div><span className="ai-pipeline-panel__live"><i />Service status available</span></header>
      <div className="ai-pipeline">
        <PipelineStep index="01" icon={Eye} title="Video input" detail="Camera or evidence file" />
        <ArrowRight className="ai-pipeline__arrow" size={18} />
        <PipelineStep index="02" icon={Focus} title="Vehicle detect" detail="YOLO26 checkpoint" active />
        <ArrowRight className="ai-pipeline__arrow" size={18} />
        <PipelineStep index="03" icon={Database} title="Crop archive" detail="Evidence ID + source metadata" active />
        <ArrowRight className="ai-pipeline__arrow" size={18} />
        <PipelineStep index="04" icon={ScanLine} title="Plate detect" detail="Dedicated .pt model" active />
        <ArrowRight className="ai-pipeline__arrow" size={18} />
        <PipelineStep index="05" icon={CloudCog} title="Hybrid OCR" detail="Google primary + Groq fallback" active />
        <ArrowRight className="ai-pipeline__arrow" size={18} />
        <PipelineStep index="06" icon={ScanEye} title="Visual profile" detail="Groq appearance intelligence" active />
        <ArrowRight className="ai-pipeline__arrow" size={18} />
        <PipelineStep index="07" icon={ShieldCheck} title="Human review" detail="Plate-backed case handoff" />
      </div>
    </section>

    <section className="ai-capabilities">
      <header><div><span className="ai-kicker">Capability register</span><h2>Analytics services</h2><p>Operational state and available evidence for each configured service.</p></div><span>{overview?.features.length ?? 0} services listed</span></header>
      <div className="ai-capability-grid">
        {(overview?.features ?? []).map((feature, index) => <FeatureCard key={feature.key} feature={feature} index={index} />)}
        {loadingOverview ? Array.from({ length: 4 }, (_, index) => <div className="ai-capability ai-skeleton" key={index} />) : null}
      </div>
    </section>

    <section className="ai-vault">
      <header className="ai-section-header">
        <div><span className="ai-kicker">Vehicle detection archive</span><h2>Latest vehicle evidence</h2><p>Newest retained crop first, with a permanent evidence ID and detector provenance.</p></div>
        <strong>{detections.total.toLocaleString("en-IN")} records</strong>
      </header>
      <div className="ai-vault__controls">
        <label className="ai-search"><Search size={16} /><input value={query} onChange={(event) => { setQuery(event.target.value); setDetectionPage(1); }} placeholder="Search track, frame, source or class…" /></label>
        <div className="ai-class-filter" aria-label="Vehicle class filter">
          {vehicleClasses.map((item) => <button type="button" key={item} className={vehicleClass === item ? "active" : ""} onClick={() => selectClass(item)}>{item === "all" ? <Layers3 size={14} /> : item === "truck" ? <Truck size={14} /> : item === "bus" ? <Bus size={14} /> : <CarFront size={14} />}{titleCase(item)}</button>)}
        </div>
        <label className="ai-confidence"><span>Minimum confidence <b>{percentage(minimumConfidence)}</b></span><input type="range" min="0.3" max="0.9" step="0.05" value={minimumConfidence} onChange={(event) => { setMinimumConfidence(Number(event.target.value)); setDetectionPage(1); }} /></label>
        <span className="ai-sort-order"><CalendarClock size={15} />Newest first</span>
      </div>
      <div className="ai-evidence-grid" aria-live="polite">
        {detections.items.map((item, index) => <DetectionCard key={item.id} item={item} index={index} onOpen={() => setSelected(item)} />)}
        {loadingDetections ? Array.from({ length: 8 }, (_, index) => <div className="ai-evidence-card ai-skeleton" key={index} />) : null}
      </div>
      {!loadingDetections && !detections.items.length ? <EmptyState icon={Search} title="No vehicle crop matches these filters" /> : null}
      <Pager page={detections.page} pages={detections.pages} onChange={setDetectionPage} />
    </section>

    <section className="ai-plate-lab">
      <header className="ai-section-header">
        <div><span className="ai-kicker">Number-plate review</span><h2>Latest plate and OCR evidence</h2><p>Newest plate crop first; each record links the detector ID, OCR service ID and source vehicle evidence.</p></div>
        <label className="ai-search ai-search--plate"><Search size={16} /><input value={plateQuery} onChange={(event) => { setPlateQuery(event.target.value); setPlatePage(1); }} placeholder="Search plate or track…" /></label>
      </header>
      <div className="ai-plate-grid">
        {plates.items.map((item, index) => <PlateCard item={item} index={index} key={item.id} />)}
        {loadingPlates ? Array.from({ length: 5 }, (_, index) => <div className="ai-plate-card ai-skeleton" key={index} />) : null}
      </div>
      {!loadingPlates && !plates.items.length ? <EmptyState icon={ScanLine} title="No plate evidence matches this search" /> : null}
      <Pager page={plates.page} pages={plates.pages} onChange={setPlatePage} />
    </section>

    <div className="ai-disclosure"><ShieldCheck size={17} /><span><strong>Operational interpretation boundary.</strong> {overview?.disclosure ?? "AI output remains model-attributed evidence and requires authorized human review."}</span></div>

    {selected ? <EvidenceModal item={selected} onClose={() => setSelected(null)} /> : null}
  </div>;
}

function Metric({ icon: Icon, label, value, note, loading, tone = "cyan" }: { icon: LucideIcon; label: string; value: string | number | undefined; note: string; loading: boolean; tone?: string }) {
  return <article className={`ai-metric ai-metric--${tone}`}><span><Icon size={19} /></span><div><small>{label}</small><strong>{loading ? "···" : typeof value === "number" ? value.toLocaleString("en-IN") : value ?? "—"}</strong><p>{note}</p></div><i /></article>;
}

function PipelineStep({ index, icon: Icon, title, detail, active = false }: { index: string; icon: LucideIcon; title: string; detail: string; active?: boolean }) {
  return <article className={active ? "active" : ""}><span><Icon size={19} /><i /></span><small>{index}</small><strong>{title}</strong><p>{detail}</p></article>;
}

function FeatureCard({ feature, index }: { feature: AIFeatureStatus; index: number }) {
  const Icon = featureIcons[feature.key] ?? BrainCircuit;
  return <article className="ai-capability" style={{ "--reveal-delay": `${index * 55}ms` } as CSSProperties}>
    <header><span><Icon size={20} /></span><em className={`ai-status ai-status--${feature.status}`}><i />{titleCase(feature.status)}</em></header>
    <h3>{feature.name}</h3><p>{feature.description}</p><footer><BadgeCheck size={14} />{feature.evidence}</footer>
  </article>;
}

function DetectionCard({ item, index, onOpen }: { item: AIDetection; index: number; onOpen: () => void }) {
  return <button type="button" className="ai-evidence-card" style={{ "--reveal-delay": `${index * 35}ms` } as CSSProperties} onClick={onOpen}>
    <span className="ai-evidence-card__image"><img src={apiMediaUrl(item.image_url)} alt={`${item.class_name} detection from ${item.source_label}`} loading="lazy" /><span>{percentage(item.confidence)} confidence</span><Maximize2 size={16} /></span>
    <span className="ai-evidence-card__body"><span><strong>{titleCase(item.class_name)}</strong><em>{item.evidence_id}</em></span><small>Track {item.track_id ?? "unassigned"} · Frame {item.frame.toLocaleString("en-IN")} · {item.width}×{item.height}px</small><small>{item.source_label}</small><span className="ai-evidence-card__provenance"><code>{item.model_id}</code><time>{evidenceTime(item.created_at)}</time></span></span>
  </button>;
}

function PlateCard({ item, index }: { item: AIPlateDetection; index: number }) {
  const ocrStatus = item.ocr_status || (item.plate_text ? "COMPLETED" : "PENDING");
  const candidates = item.ocr_candidates ?? [];
  const decision = item.ocr_decision ? titleCase(item.ocr_decision) : titleCase(ocrStatus);
  return <article className={`ai-plate-card${item.ocr_review_required ? " ai-plate-card--review" : ""}`} style={{ "--reveal-delay": `${index * 45}ms` } as CSSProperties}>
    <div className="ai-plate-card__decision"><span>{decision}</span><strong>{item.ocr_review_required ? "OFFICER REVIEW REQUIRED" : `Selected: ${titleCase(item.ocr_selected_provider ?? item.ocr_provider)}`}</strong>{item.ocr_decision_reason ? <p>{item.ocr_decision_reason}</p> : null}</div>
    {candidates.length ? <div className="ai-plate-card__candidates">{candidates.map((candidate) => <div key={candidate.provider}><span><b>{candidate.provider}</b><small>{titleCase(candidate.status)}</small></span><strong>{candidate.normalized_text || candidate.raw_text || (candidate.status === "no_text" || candidate.status === "completed" ? "No text returned" : candidate.status === "failed" ? "Provider error" : "Not invoked")}</strong><em>{candidate.confidence == null ? "No score" : percentage(candidate.confidence)}{candidate.processing_ms == null ? "" : ` / ${Math.round(candidate.processing_ms)} ms`}</em></div>)}</div> : null}
    <div className="ai-plate-card__image"><img src={apiMediaUrl(item.image_url)} alt={`Detected plate ${item.plate_text ?? "requiring review"}`} loading="lazy" />{item.source_vehicle_image_url ? <img className="ai-plate-card__vehicle" src={apiMediaUrl(item.source_vehicle_image_url)} alt={`Source vehicle ${item.source_vehicle_evidence_id ?? "evidence"}`} loading="lazy" title="Linked source vehicle crop" /> : null}<span><ScanLine size={14} />PLATE CROP</span></div>
    <div className="ai-plate-card__read"><small>{item.evidence_id} · {titleCase(ocrStatus)}</small><strong>{item.plate_text || (ocrStatus === "FAILED" ? "OCR FAILED" : "REVIEW REQUIRED")}</strong><em>{item.ocr_provider.includes("google-cloud-vision") || item.ocr_provider.includes("google_cloud_vision") ? "GOOGLE CLOUD VISION" : titleCase(item.ocr_provider)}</em></div>
    <div className="ai-plate-card__metrics"><span><small>OCR confidence</small><b>{percentage(item.ocr_confidence)}</b></span><span><small>Consensus</small><b>{item.ocr_consensus_count > 1 ? `${item.ocr_consensus_count} reads` : "Single read"}</b></span><span><small>Track</small><b>#{item.track_id ?? "—"}</b></span></div>
    <footer><span>Frame {item.frame.toLocaleString("en-IN")} · {item.source_label}{item.source_vehicle_evidence_id ? ` · ${item.source_vehicle_evidence_id}` : ""}</span><span><code>{item.detector_model_id}</code> + <code>{item.ocr_model_id}</code> · {evidenceTime(item.created_at)}</span></footer>
  </article>;
}

function Pager({ page, pages, onChange }: { page: number; pages: number; onChange: (page: number) => void }) {
  if (pages <= 1) return null;
  return <nav className="ai-pager" aria-label="Evidence pagination"><button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)}><ChevronLeft size={16} />Previous</button><span>Page <strong>{page}</strong> of {pages}</span><button type="button" disabled={page >= pages} onClick={() => onChange(page + 1)}>Next<ChevronRight size={16} /></button></nav>;
}

function EmptyState({ icon: Icon, title }: { icon: LucideIcon; title: string }) {
  return <div className="ai-empty"><Icon size={23} /><strong>{title}</strong><span>Adjust the search or confidence filter to widen the evidence view.</span></div>;
}

function EvidenceModal({ item, onClose }: { item: AIDetection; onClose: () => void }) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  return <div className="ai-modal" role="dialog" aria-modal="true" aria-label="Detection evidence detail" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <article><header><div><span className="ai-kicker">Evidence record {item.evidence_id}</span><h2>{titleCase(item.class_name)} detection</h2></div><button type="button" onClick={onClose} aria-label="Close evidence detail"><X size={19} /></button></header><div className="ai-modal__image"><img src={apiMediaUrl(item.image_url)} alt={`${item.class_name} evidence`} /><span><Focus size={16} />Detector crop · {percentage(item.confidence)}</span></div><dl><div><dt>Detector</dt><dd>{item.model_id} · {item.model_name}</dd></div><div><dt>Captured</dt><dd>{evidenceTime(item.created_at)}</dd></div><div><dt>Track identity</dt><dd>#{item.track_id ?? "Unassigned"}</dd></div><div><dt>Source</dt><dd>{item.source_label}</dd></div><div><dt>Frame / time</dt><dd>{item.frame.toLocaleString("en-IN")} · {(item.time_ms / 1000).toFixed(2)}s</dd></div><div><dt>Crop dimensions</dt><dd>{item.width} × {item.height}px</dd></div><div><dt>Bounding box</dt><dd>{item.box.map(Math.round).join(", ")}</dd></div><div><dt>Observed confidence</dt><dd>{percentage(item.confidence)}</dd></div></dl><footer><ShieldCheck size={15} />Stored model output; identity and enforcement decisions require authorized human review.</footer></article>
  </div>;
}
