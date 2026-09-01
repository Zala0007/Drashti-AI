import {
  AlertTriangle, ArrowRight, BrainCircuit, Camera, Check, ChevronLeft,
  ChevronRight, Clock3, Database, Eye, ImageOff, LoaderCircle, MapPinned, Search,
  RotateCcw, ShieldCheck, Sparkles, X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { apiMediaUrl, ApiError, investigationApi, visualIntelligenceApi } from "../lib/api";
import type {
  VisualIntelligenceStatus, VisualSearchFilters, VisualSearchResponse, VisualSearchResult,
} from "../types/visualIntelligence";
import { Modal } from "../components/Modal";

const suggestions = [
  "Red vehicles", "Damaged vehicles", "White SUV with roof rack",
  "Black sedan with rear damage", "Bike with broken headlight", "Vehicle with unreadable plate",
];
const vehicleTypes = ["", "car", "sedan", "hatchback", "suv", "truck", "bus", "motorcycle"];
const colors = ["", "red", "white", "black", "silver", "grey", "blue", "green", "yellow", "brown"];

const titleCase = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const safeMessage = (error: unknown) => error instanceof ApiError ? error.message : "Visual Intelligence is temporarily unavailable.";
const observedTime = (value: string) => {
  const normalized = value.includes("T") ? value : value.replace(" ", "T") + "Z";
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};

export function VisualIntelligencePage() {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<VisualSearchFilters>({});
  const [response, setResponse] = useState<VisualSearchResponse | null>(null);
  const [status, setStatus] = useState<VisualIntelligenceStatus | null>(null);
  const [selected, setSelected] = useState<VisualSearchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [backfilling, setBackfilling] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const loadStatus = useCallback(() => visualIntelligenceApi.status().then(setStatus).catch(() => undefined), []);
  const search = useCallback(async (nextQuery: string, nextFilters: VisualSearchFilters, nextPage = 1) => {
    setLoading(true);
    setError(null);
    try {
      const result = await visualIntelligenceApi.search(nextQuery, nextFilters, nextPage, 18);
      setResponse(result);
      setQuery(nextQuery);
      setPage(nextPage);
    } catch (cause) {
      setError(safeMessage(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void Promise.all([loadStatus(), search("", {}, 1)]);
  }, [loadStatus, search]);

  useEffect(() => {
    if (!status || status.pending + status.processing + status.queue_depth === 0) return;
    const timer = window.setInterval(() => void loadStatus(), 3000);
    return () => window.clearInterval(timer);
  }, [loadStatus, status]);

  useEffect(() => {
    const controller = new AbortController();
    const refreshLiveIntelligence = () => {
      if (document.visibilityState !== "visible") return;
      void visualIntelligenceApi.status(controller.signal).then(setStatus).catch(() => undefined);
      void visualIntelligenceApi.search(query, filters, page, 18, controller.signal)
        .then(setResponse)
        .catch(() => undefined);
    };
    const timer = window.setInterval(refreshLiveIntelligence, 6000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [filters, page, query]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void search(draft.trim(), filters, 1);
  };

  const updateFilter = (key: keyof VisualSearchFilters, value: string) => {
    const next = { ...filters, [key]: value || undefined };
    setFilters(next);
    void search(query, next, 1);
  };

  const backfill = async () => {
    setBackfilling(true);
    setError(null);
    try {
      const result = await visualIntelligenceApi.backfill(24);
      setNotice(result.message);
      await loadStatus();
    } catch (cause) {
      setError(safeMessage(cause));
    } finally {
      setBackfilling(false);
    }
  };

  const retryFailures = async () => {
    setBackfilling(true);
    setError(null);
    try {
      const result = await visualIntelligenceApi.backfill(24, true);
      setNotice(result.message);
      await loadStatus();
    } catch (cause) {
      setError(safeMessage(cause));
    } finally {
      setBackfilling(false);
    }
  };

  const damageCount = useMemo(() => response?.results.filter((item) => ["possible", "visible"].includes(item.damage_status)).length ?? 0, [response]);

  return <div className="visual-page">
    <section className="visual-hero">
      <div className="visual-hero__copy">
        <span className="visual-eyebrow"><BrainCircuit size={14} /> Visual Intelligence Engine</span>
        <h1>Describe the vehicle.<br /><em>Search what cameras have seen.</em></h1>
        <p>Search pre-analyzed vehicle evidence by appearance, visible condition, camera context and plate visibility—without sending the archive to AI on every search.</p>
        <form className="visual-search" onSubmit={submit}>
          <Search size={22} aria-hidden="true" />
          <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="e.g. red SUV with damaged front bumper and black roof rails" aria-label="Search by visual appearance" />
          <button type="submit" disabled={loading}>{loading ? <LoaderCircle className="spin" size={18} /> : <ArrowRight size={18} />} Search evidence</button>
        </form>
        <div className="visual-suggestions">{suggestions.map((item) => <button type="button" key={item} onClick={() => { setDraft(item); void search(item, filters, 1); }}>{item}</button>)}</div>
      </div>
      <aside className="visual-provider-card">
        <header><span><Sparkles size={19} /></span><div><small>Enrichment service</small><strong>{status?.configured ? "GROQ VISION CONFIGURED" : "CONFIGURATION REQUIRED"}</strong></div></header>
        <dl>
          <div><dt>Analyzed</dt><dd>{status?.completed.toLocaleString("en-IN") ?? "—"}</dd></div>
          <div><dt>Queued</dt><dd>{((status?.pending ?? 0) + (status?.queue_depth ?? 0)).toLocaleString("en-IN")}</dd></div>
          <div><dt>Vehicle crops</dt><dd>{status?.total_vehicle_crops.toLocaleString("en-IN") ?? "—"}</dd></div>
          <div><dt>Failures</dt><dd>{status?.failed.toLocaleString("en-IN") ?? "—"}</dd></div>
        </dl>
        <small>{status?.model ?? "Backend-only provider"} · {status?.prompt_version ?? "vehicle_visual_profile_v1"}</small>
        <div className="visual-provider-actions"><button type="button" onClick={() => void backfill()} disabled={backfilling || !status?.configured}>{backfilling ? <LoaderCircle className="spin" size={15} /> : <Database size={15} />} Analyze next crop batch</button>{status?.failed ? <button type="button" onClick={() => void retryFailures()} disabled={backfilling || !status.configured}><RotateCcw size={14} /> Retry {status.failed} failed</button> : null}</div>
      </aside>
    </section>

    {error ? <div className="visual-alert"><AlertTriangle size={17} /><span><strong>Visual Intelligence notice</strong>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Dismiss"><X size={16} /></button></div> : null}
    {notice ? <div className="visual-notice"><Check size={16} />{notice}<button type="button" onClick={() => setNotice(null)} aria-label="Dismiss"><X size={14} /></button></div> : null}

    <section className="visual-metrics">
      <Metric label="Matching evidence" value={response?.total_results ?? 0} note="retrieval-selected records" icon={Search} />
      <Metric label="Possible damage" value={damageCount} note="in displayed results" icon={AlertTriangle} tone="amber" />
      <Metric label="Readable plates" value={response?.results.filter((item) => item.anpr_plate).length ?? 0} note="ANPR remains authoritative" icon={Eye} tone="green" />
      <Metric label="Processing" value={(status?.processing ?? 0) + (status?.pending ?? 0)} note="non-blocking enrichment" icon={BrainCircuit} tone="violet" />
    </section>

    <section className="visual-workspace">
      <header className="visual-workspace__header">
        <div><span className="visual-eyebrow">Searchable vehicle intelligence</span><h2>{query ? `Matches for “${query}”` : "Analyzed vehicle gallery"}</h2><p>{response?.summary ?? "Loading visual intelligence…"}</p></div>
        <span><ShieldCheck size={15} /> Retrieval decides results · AI descriptions assist review</span>
      </header>
      <div className="visual-filterbar">
        <label><span>Vehicle type</span><select value={filters.vehicle_type ?? ""} onChange={(event) => updateFilter("vehicle_type", event.target.value)}>{vehicleTypes.map((item) => <option value={item} key={item}>{item ? titleCase(item) : "All types"}</option>)}</select></label>
        <label><span>Colour</span><select value={filters.primary_color ?? ""} onChange={(event) => updateFilter("primary_color", event.target.value)}>{colors.map((item) => <option value={item} key={item}>{item ? titleCase(item) : "All colours"}</option>)}</select></label>
        <label><span>Visible condition</span><select value={filters.damage_status ?? ""} onChange={(event) => updateFilter("damage_status", event.target.value)}><option value="">Any condition</option><option value="none_obvious">No obvious damage</option><option value="possible">Possible damage</option><option value="visible">Visible deformation</option><option value="uncertain">Uncertain</option></select></label>
        <label><span>Damage location</span><input value={filters.damage_location ?? ""} onChange={(event) => updateFilter("damage_location", event.target.value)} placeholder="e.g. front bumper" /></label>
        <label><span>Plate visibility</span><select value={filters.plate_visibility ?? ""} onChange={(event) => updateFilter("plate_visibility", event.target.value)}><option value="">Any visibility</option><option value="readable">Readable</option><option value="partial">Partial</option><option value="unreadable">Unreadable</option><option value="not_visible">Not visible</option></select></label>
        <label><span>Image quality</span><select value={filters.image_quality ?? ""} onChange={(event) => updateFilter("image_quality", event.target.value)}><option value="">Any quality</option><option value="good">Good</option><option value="fair">Fair</option><option value="poor">Poor</option></select></label>
        <label><span>Camera ID</span><input value={filters.camera_ids?.[0] ?? ""} onChange={(event) => { const next = { ...filters, camera_ids: event.target.value ? [event.target.value] : undefined }; setFilters(next); void search(query, next, 1); }} placeholder="Camera UUID or code" /></label>
        <label><span>From date</span><input type="date" value={filters.date_from ?? ""} onChange={(event) => updateFilter("date_from", event.target.value)} /></label>
        <label><span>To date</span><input type="date" value={filters.date_to ?? ""} onChange={(event) => updateFilter("date_to", event.target.value)} /></label>
        <label><span>From time</span><input type="time" step="1" value={filters.time_from ?? ""} onChange={(event) => updateFilter("time_from", event.target.value)} /></label>
        <label><span>To time</span><input type="time" step="1" value={filters.time_to ?? ""} onChange={(event) => updateFilter("time_to", event.target.value)} /></label>
        <button type="button" onClick={() => { setFilters({}); void search(query, {}, 1); }}>Clear filters</button>
      </div>

      <div className="visual-grid" aria-live="polite">
        {response?.results.map((item) => <VisualCard item={item} key={item.id} onOpen={() => setSelected(item)} onNotice={setError} />)}
        {loading ? Array.from({ length: 6 }, (_, index) => <div className="visual-card visual-card--loading" key={index} />) : null}
      </div>
      {!loading && !response?.results.length ? <div className="visual-empty"><ImageOff size={28} /><strong>No vehicles matched the current description.</strong><p>Remove one attribute, broaden the vehicle type, or clear the filters.</p></div> : null}
      {response && response.pages > 1 ? <nav className="visual-pager"><button type="button" disabled={page <= 1} onClick={() => void search(query, filters, page - 1)}><ChevronLeft size={15} /> Previous</button><span>Page <strong>{page}</strong> of {response.pages}</span><button type="button" disabled={page >= response.pages} onClick={() => void search(query, filters, page + 1)}>Next <ChevronRight size={15} /></button></nav> : null}
    </section>

    {selected ? <VisualProfile item={selected} onClose={() => setSelected(null)} /> : null}
  </div>;
}

function Metric({ label, value, note, icon: Icon, tone = "cyan" }: { label: string; value: number; note: string; icon: typeof Search; tone?: string }) {
  return <article className={`visual-metric visual-metric--${tone}`}><span><Icon size={18} /></span><div><small>{label}</small><strong>{value.toLocaleString("en-IN")}</strong><p>{note}</p></div></article>;
}

function VisualCard({ item, onOpen, onNotice }: { item: VisualSearchResult; onOpen: () => void; onNotice: (message: string) => void }) {
  const map = () => { sessionStorage.setItem("drishti-visual-camera", item.camera_id); window.location.hash = "#/gis"; };
  const investigate = async () => {
    if (item.anpr_plate) {
      await investigationApi.create({ target_plate: item.anpr_plate, priority: "high", reason: `Visual Intelligence candidate ${item.event_id}: ${item.short_description}` });
    } else {
      onNotice("This evidence has no verified plate. Open it on the GIS map for review; visual-only case creation requires the planned ReID handoff.");
      return;
    }
    window.location.hash = "#/investigation";
  };
  return <article className="visual-card">
    <button type="button" className="visual-card__image" onClick={onOpen}><img src={apiMediaUrl(item.vehicle_crop_uri)} alt={item.short_description} loading="lazy" /><span className={`visual-match visual-match--${item.match_level.toLowerCase()}`}>Match {item.match_level}</span><em>{item.event_id}</em></button>
    <div className="visual-card__body">
      <header><div><small>{titleCase(item.primary_color)} · {titleCase(item.vehicle_view)}</small><h3>{titleCase(item.primary_color)} {item.vehicle_type.toLowerCase() === "suv" ? "SUV" : titleCase(item.vehicle_type)}</h3></div><strong>{item.anpr_plate || "PLATE UNREADABLE"}</strong></header>
      <p>{item.short_description}</p>
      <div className="visual-tags">{[...item.distinctive_features, ...item.accessories].slice(0, 3).map((tag) => <span key={tag}>{titleCase(tag)}</span>)}</div>
      <ul>{item.match_reasons.slice(0, 3).map((reason) => <li key={reason}><Check size={12} />{reason}</li>)}</ul>
      <footer><span><Camera size={13} />{item.camera_id.slice(0, 18)}</span><span><Clock3 size={13} />{observedTime(item.observed_at)}</span></footer>
    </div>
    <div className="visual-card__actions"><button type="button" onClick={onOpen}>View profile</button><button type="button" onClick={map}><MapPinned size={14} /> Map</button><button type="button" onClick={() => void investigate()}>{item.anpr_plate ? "Investigate" : "Review route"} <ArrowRight size={14} /></button></div>
  </article>;
}

function VisualProfile({ item, onClose }: { item: VisualSearchResult; onClose: () => void }) {
  return <Modal open onClose={onClose} title="Vehicle visual profile" eyebrow={`${item.event_id} · Investigator verification`} wide>
    <div className="modal__body visual-profile">
      <section className="visual-profile__media">
        <figure><figcaption>Vehicle crop · Original evidence</figcaption><img src={apiMediaUrl(item.vehicle_crop_uri)} alt={item.short_description} /></figure>
        <figure className="visual-profile__plate"><figcaption>Number plate crop</figcaption>{item.plate_crop_uri ? <img src={apiMediaUrl(item.plate_crop_uri)} alt={`Plate ${item.anpr_plate ?? "requiring review"}`} /> : <span><ImageOff size={20} />No linked plate crop</span>}</figure>
      </section>
      <section className="visual-profile__facts">
        <dl><Fact label="Vehicle type" value={`${titleCase(item.vehicle_type)} · ${titleCase(item.vehicle_type_confidence)}`} /><Fact label="Primary colour" value={titleCase(item.primary_color)} /><Fact label="Registration" value={item.anpr_plate || "Unavailable"} /><Fact label="Visual condition" value={titleCase(item.visual_condition)} /><Fact label="View" value={titleCase(item.vehicle_view)} /><Fact label="Image quality" value={titleCase(item.image_quality)} /><Fact label="Plate visibility" value={titleCase(item.plate_visibility)} /><Fact label="Lighting" value={titleCase(item.lighting_condition)} /><Fact label="Occlusion" value={titleCase(item.occlusion)} /><Fact label="AI confidence" value={titleCase(item.analysis_confidence)} /></dl>
        <div className="visual-profile__description"><span className="visual-eyebrow">AI description</span><p>{item.detailed_description}</p></div>
        <div className="visual-profile__features"><strong>Distinctive features</strong>{item.distinctive_features.length ? <ul>{item.distinctive_features.map((feature) => <li key={feature}><Check size={13} />{titleCase(feature)}</li>)}</ul> : <p>No distinctive feature confidently identified.</p>}</div>
        <div className="visual-profile__provenance"><ShieldCheck size={15} /><span><strong>{item.vlm_provider.toUpperCase()} · {item.vlm_model}</strong><small>{item.vlm_prompt_version} · descriptions assist investigation; original imagery remains evidence.</small></span></div>
      </section>
    </div>
  </Modal>;
}

function Fact({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
