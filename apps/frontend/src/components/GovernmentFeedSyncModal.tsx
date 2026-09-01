import {
  AlertTriangle,
  CheckCircle2,
  CloudDownload,
  DatabaseZap,
  LoaderCircle,
  MapPinned,
  RadioTower,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ApiError, federationApi } from "../lib/api";
import type {
  GovernmentFeedCatalogue,
  GovernmentFeedSyncResult,
} from "../types/federation";
import { Modal } from "./Modal";

interface GovernmentFeedSyncModalProps {
  open: boolean;
  onClose: () => void;
  onSynced: () => void;
}

const safeMessage = (error: unknown) => error instanceof ApiError
  ? error.message
  : "The government feed catalogue could not be reached.";

export function GovernmentFeedSyncModal({ open, onClose, onSynced }: GovernmentFeedSyncModalProps) {
  const [catalogue, setCatalogue] = useState<GovernmentFeedCatalogue | null>(null);
  const [result, setResult] = useState<GovernmentFeedSyncResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      setCatalogue(await federationApi.governmentFeedCatalogue(signal));
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) {
        setError(safeMessage(caught));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setResult(null);
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, open]);

  const sync = async () => {
    setSyncing(true);
    setError(null);
    try {
      const synced = await federationApi.syncGovernmentFeeds();
      setResult(synced);
      setCatalogue((current) => current ? { ...current, items: synced.items } : current);
      onSynced();
    } catch (caught) {
      setError(safeMessage(caught));
    } finally {
      setSyncing(false);
    }
  };

  const close = () => {
    if (!syncing) onClose();
  };

  return (
    <Modal
      open={open}
      onClose={close}
      busy={syncing}
      title="Government evaluation feed grid"
      eyebrow="P0.3 / Dynamic catalogue federation"
      wide
    >
      <div className="modal__body government-feed-sync">
        <div className="government-feed-sync__trust">
          <span><DatabaseZap size={17} /><strong>Catalogue-driven</strong><small>Camera IDs are discovered at request time</small></span>
          <span><ShieldCheck size={17} /><strong>Secret-safe</strong><small>Endpoints are encrypted and never returned</small></span>
          <span><RadioTower size={17} /><strong>Dual transport</strong><small>RTSP/TCP primary with HTTPS HLS fallback</small></span>
        </div>

        {error ? <div className="government-feed-sync__error" role="alert"><AlertTriangle size={18} /><span><strong>Catalogue operation failed</strong><small>{error}</small></span><button type="button" onClick={() => void load()}><RefreshCw size={14} />Retry</button></div> : null}

        {loading && !catalogue ? <div className="government-feed-sync__loading"><LoaderCircle className="spin" size={24} /><strong>Reading the live government catalogue</strong><small>Validating inventory metadata and stream ownership boundaries…</small></div> : null}

        {!loading && catalogue && !catalogue.configured ? (
          <div className="government-feed-sync__loading"><AlertTriangle size={24} /><strong>Catalogue connector is not configured</strong><small>Set GOVERNMENT_FEED_CATALOGUE_URL on the backend before discovery.</small></div>
        ) : null}

        {catalogue?.configured ? (
          <>
            <div className="government-feed-summary">
              <Summary label="Discovered" value={catalogue.total} detail="Current catalogue contract" />
              <Summary label="Live now" value={catalogue.live} detail="Provider-reported status" tone="green" />
              <Summary label="H.264" value={catalogue.h264} detail="Known AVC feeds" />
              <Summary label="H.265" value={catalogue.h265} detail="Known HEVC feeds" tone="violet" />
              <Summary label="Metadata pending" value={catalogue.metadata_pending} detail="Probed during decode" tone="amber" />
            </div>

            {result ? (
              <div className="government-sync-result" role="status">
                <CheckCircle2 size={19} />
                <span><strong>{result.discovered} feeds synchronized into Drishti AI</strong><small>{result.cameras_created} cameras created · {result.cameras_updated} updated · {result.connections_created} encrypted profiles created</small></span>
              </div>
            ) : null}

            <div className="government-feed-table-wrap">
              <table className="government-feed-table">
                <thead><tr><th>Feed</th><th>Provider location</th><th>Media</th><th>Status</th><th>Drishti state</th></tr></thead>
                <tbody>
                  {catalogue.items.map((feed) => (
                    <tr key={feed.external_id}>
                      <td><strong>{feed.name}</strong><small>ID {feed.external_id}</small></td>
                      <td>{feed.location}</td>
                      <td><strong>{feed.codec?.toUpperCase() ?? "Pending"}</strong><small>{feed.width && feed.height ? `${feed.width}×${feed.height}` : "Resolution pending"}{feed.fps ? ` · ${feed.fps.toFixed(1)} fps` : ""}</small></td>
                      <td><span className={`government-feed-live${feed.live ? " is-live" : ""}`}><i />{feed.live ? "Live" : "Offline"}</span></td>
                      <td><span className={`government-feed-state government-feed-state--${feed.sync_state}`}>{feed.sync_state === "onboarded" ? <CheckCircle2 size={13} /> : <CloudDownload size={13} />}{feed.sync_state}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="government-feed-geo-note"><MapPinned size={17} /><span><strong>GIS verification boundary</strong><small>The provider supplies location text but not coordinates. Drishti marks imported centroids as provisional so they cannot be mistaken for surveyed camera positions.</small></span></div>
          </>
        ) : null}
      </div>
      <footer className="modal__footer">
        <p><ShieldCheck size={14} /> No raw RTSP, HLS, WHEP, credential, or token is exposed to this browser.</p>
        <button type="button" className="button button--secondary" onClick={close} disabled={syncing}>Close</button>
        <button type="button" className="button button--primary" onClick={() => void sync()} disabled={syncing || loading || !catalogue?.configured || !catalogue.total}>
          {syncing ? <LoaderCircle className="spin" size={16} /> : <CloudDownload size={16} />}
          {syncing ? "Encrypting and onboarding…" : result ? "Synchronize again" : `Onboard ${catalogue?.total ?? 0} feeds`}
        </button>
      </footer>
    </Modal>
  );
}

function Summary({ label, value, detail, tone = "neutral" }: { label: string; value: number; detail: string; tone?: "neutral" | "green" | "violet" | "amber" }) {
  return <article className={`government-feed-summary__item government-feed-summary__item--${tone}`}><small>{label}</small><strong>{value.toLocaleString("en-IN")}</strong><span>{detail}</span></article>;
}
