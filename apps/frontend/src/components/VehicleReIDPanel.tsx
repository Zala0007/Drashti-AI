import {
  AlertTriangle,
  BadgeCheck,
  CarFront,
  Check,
  Eye,
  Fingerprint,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { advancedApi, aiApi, apiMediaUrl, ApiError } from "../lib/api";
import { formatTimestamp, titleCase } from "../lib/format";
import type { ReIDMatch, ReIDResult, VehicleObservation } from "../types/advanced";

export function VehicleReIDPanel({
  investigationId,
  onConfirmed,
}: {
  investigationId: string;
  onConfirmed: () => void;
}) {
  const [result, setResult] = useState<ReIDResult | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demoDisclosure, setDemoDisclosure] = useState<string | null>(null);
  const [referenceCrops, setReferenceCrops] = useState<string[]>([]);

  const rank = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await advancedApi.rankReID(investigationId);
      const items = Array.isArray(next.items) ? next.items : [];
      setResult({ ...next, items });
      setSelectedId((current) => items.some((item) => item.id === current)
        ? current
        : items[0]?.id ?? null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Vehicle similarity ranking failed.");
    } finally {
      setLoading(false);
    }
  }, [investigationId]);

  useEffect(() => { void rank(); }, [rank]);

  useEffect(() => {
    const controller = new AbortController();
    aiApi.detections({ className: "car", minimumConfidence: 0.65, page: 1, pageSize: 6 }, controller.signal)
      .then((page) => {
        const preferred = [page.items[1], page.items[3]].filter(Boolean);
        const items = preferred.length >= 2 ? preferred : page.items.slice(0, 2);
        setReferenceCrops(items.map((item) => apiMediaUrl(item.image_url)));
      })
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setReferenceCrops([]);
      });
    return () => controller.abort();
  }, []);

  const loadDemo = async () => {
    setBusy(true);
    try {
      const seeded = await advancedApi.seedReIDDemo(investigationId);
      setDemoDisclosure(seeded.disclosure);
      await rank();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The disclosed scenario could not be prepared.");
    } finally {
      setBusy(false);
    }
  };

  const review = async (match: ReIDMatch, status: "confirmed" | "rejected" | "candidate") => {
    setBusy(true);
    setError(null);
    try {
      const note = status === "confirmed"
        ? "Investigator reviewed visual, temporal, route and vehicle attributes in the controlled console."
        : status === "rejected"
          ? "Investigator rejected this candidate after manual comparison."
          : "Candidate retained for additional investigator review.";
      const updated = await advancedApi.reviewReID(match.id, status, note);
      setResult((current) => current ? {
        ...current,
        items: current.items.map((item) => item.id === updated.id ? updated : item),
      } : current);
      if (status === "confirmed") onConfirmed();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The review decision was not saved.");
    } finally {
      setBusy(false);
    }
  };

  const selected = result?.items.find((item) => item.id === selectedId) ?? result?.items[0];
  return (
    <section className="reid-console">
      <header className="reid-console__header">
        <div className="reid-console__title">
          <span className="reid-console__scanner"><ScanLine size={24} /><i /></span>
          <div><span className="panel-kicker">P-S01 · Human-reviewed intelligence</span><h2>Vehicle Re-Identification</h2><p>Recover a target when the registration is hidden, unreadable, or changed.</p></div>
        </div>
        <div className="reid-console__posture"><ShieldCheck size={16} /><span><small>Decision boundary</small><strong>Machine ranks · investigator confirms</strong></span></div>
      </header>

      {error ? <div className="advanced-alert"><AlertTriangle size={16} />{error}</div> : null}
      {demoDisclosure ? <div className="advanced-disclosure"><Sparkles size={15} /><span><strong>Disclosed scenario.</strong> {demoDisclosure}</span></div> : null}

      {loading ? <div className="advanced-loading"><RefreshCw className="spin" size={20} />Comparing quality-gated observations…</div>
        : !selected ? (
          <div className="reid-empty"><CarFront size={34} /><div><strong>No quality-gated vehicle profile available</strong><p>Live analytics can publish embeddings through the provider-neutral ingestion contract. For this offline deployment, use the clearly labelled judge scenario.</p></div><button className="button button--primary" type="button" onClick={loadDemo} disabled={busy}><Sparkles size={16} />Load disclosed ReID scenario</button></div>
        ) : (
          <div className="reid-console__body">
            <div className="reid-comparison">
              <ObservationCard label="Target profile" observation={selected.target} tone="target" imageUrl={referenceCrops[0]} />
              <div className="reid-score-orbit"><span>{Math.round(selected.technical_score * 100)}</span><small>technical score</small><i /><b /></div>
              <ObservationCard label="Candidate observation" observation={selected.candidate} tone="candidate" imageUrl={referenceCrops[1]} />
            </div>
            <aside className="reid-decision">
              <header><span><Fingerprint size={17} />Ranked explanation</span><b className={`advanced-tone advanced-tone--${selected.assessment}`}>{selected.assessment.toUpperCase()}</b></header>
              <div className="reid-signals">
                <Signal label="Visual" value={selected.visual_similarity} />
                <Signal label="Temporal" value={selected.temporal_feasibility} />
                <Signal label="Route" value={selected.route_feasibility} />
                <Signal label="Plate" value={selected.plate_similarity} unavailable="Unreadable" />
              </div>
              <ul>{selected.reasons.map((reason) => <li key={reason}><Eye size={13} />{reason}</li>)}</ul>
              <div className="reid-review-actions">
                <button type="button" className="confirm" disabled={busy || selected.status === "confirmed"} onClick={() => void review(selected, "confirmed")}><Check size={15} />Confirm match</button>
                <button type="button" disabled={busy} onClick={() => void review(selected, "candidate")}><BadgeCheck size={15} />Keep candidate</button>
                <button type="button" className="reject" disabled={busy || selected.status === "rejected"} onClick={() => void review(selected, "rejected")}><X size={15} />Reject</button>
              </div>
              <footer>{selected.reviewed_at ? `Reviewed by ${selected.reviewed_by} · ${formatTimestamp(selected.reviewed_at)}` : "No automated confirmation. A review action is required."}</footer>
            </aside>
            <div className="reid-candidate-strip">
              {result?.items.map((item, index) => <button key={item.id} type="button" className={item.id === selected.id ? "active" : ""} onClick={() => setSelectedId(item.id)}><b>{String(index + 1).padStart(2, "0")}</b><span><strong>{item.candidate.camera.camera_code}</strong><small>{titleCase(item.candidate.colour ?? "unknown")} {titleCase(item.candidate.vehicle_class ?? "vehicle")}</small></span><em>{Math.round(item.technical_score * 100)}</em></button>)}
            </div>
          </div>
        )}
      <footer className="reid-console__disclosure">{result?.disclosure ?? "Similarity profiles are optional inputs; missing signals are omitted and weights are renormalized."}{referenceCrops.length ? " Representative retained crops from the local evidence archive are used for this disclosed presentation view." : ""}</footer>
    </section>
  );
}

function ObservationCard({ label, observation, tone, imageUrl }: { label: string; observation: VehicleObservation; tone: string; imageUrl?: string }) {
  return <article className={`reid-observation reid-observation--${tone}`}><header><span>{label}</span><b>{Math.round(observation.quality_score * 100)}% quality</b></header><div className="reid-observation__visual">{imageUrl ? <img src={imageUrl} alt={`${label} representative vehicle crop`} /> : <CarFront size={58} />}<span><ScanLine size={16} />{imageUrl ? "Retained evidence crop" : observation.crop_available ? "Controlled crop indexed" : "Crop not retained"}</span></div><div className="reid-observation__identity"><strong>{observation.track_id ?? "Unassigned track"}</strong><small>{observation.camera.camera_name}</small><code>{observation.plate_text || "PLATE UNREADABLE"}</code></div><dl><div><dt>Observed</dt><dd>{formatTimestamp(observation.observed_at)}</dd></div><div><dt>Vehicle</dt><dd>{titleCase(`${observation.colour ?? "unknown"} ${observation.vehicle_class ?? "vehicle"}`)}</dd></div><div><dt>Model</dt><dd>{observation.model_version ?? "Metadata unavailable"}</dd></div></dl></article>;
}

function Signal({ label, value, unavailable = "Unavailable" }: { label: string; value?: number | null; unavailable?: string }) {
  return <span><small>{label}</small><strong>{value == null ? unavailable : `${Math.round(value * 100)}%`}</strong><i style={{ width: value == null ? "0%" : `${Math.round(value * 100)}%` }} /></span>;
}
