import {
  Activity,
  BrainCircuit,
  Building2,
  CalendarClock,
  Camera,
  Clock3,
  Database,
  FileClock,
  MapPin,
  Network,
  Radio,
  Server,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, registryApi } from "../lib/api";
import { cameraHealth, departmentLabel, formatTimestamp, relativeTime, titleCase } from "../lib/format";
import type { AuditEntry, Camera as CameraRecord } from "../types/registry";
import { ErrorState, LoadingState } from "./Feedback";
import { StatusBadge } from "./StatusBadge";

interface CameraDetailDrawerProps {
  cameraId: string | null;
  onClose: () => void;
}

interface DetailLoadState {
  id: string | null;
  camera: CameraRecord | null;
  loading: boolean;
  error: string | null;
}

interface AuditLoadState {
  id: string | null;
  items: AuditEntry[];
  error: boolean;
}

export function CameraDetailDrawer({ cameraId, onClose }: CameraDetailDrawerProps) {
  const [detailState, setDetailState] = useState<DetailLoadState>({
    id: null,
    camera: null,
    loading: false,
    error: null,
  });
  const [auditState, setAuditState] = useState<AuditLoadState>({
    id: null,
    items: [],
    error: false,
  });
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!cameraId) {
      setDetailState({ id: null, camera: null, loading: false, error: null });
      setAuditState({ id: null, items: [], error: false });
      return;
    }
    const controller = new AbortController();
    setDetailState({ id: cameraId, camera: null, loading: true, error: null });
    setAuditState({ id: cameraId, items: [], error: false });
    registryApi.camera(cameraId, controller.signal)
      .then((camera) => {
        setDetailState((current) => current.id === cameraId
          ? { id: cameraId, camera, loading: false, error: null }
          : current);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        const message = cause instanceof ApiError
          ? cause.message
          : "Camera details could not be loaded.";
        setDetailState((current) => current.id === cameraId
          ? { id: cameraId, camera: null, loading: false, error: message }
          : current);
      });
    registryApi.audit(cameraId, controller.signal)
      .then((items) => {
        setAuditState((current) => current.id === cameraId
          ? { id: cameraId, items, error: false }
          : current);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setAuditState((current) => current.id === cameraId
          ? { id: cameraId, items: [], error: true }
          : current);
      });
    return () => controller.abort();
  }, [cameraId, reload]);

  useEffect(() => {
    if (!cameraId) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [cameraId, onClose]);

  if (!cameraId) return null;
  const isCurrentDetail = detailState.id === cameraId;
  const camera = isCurrentDetail ? detailState.camera : null;
  const loading = !isCurrentDetail || detailState.loading;
  const error = isCurrentDetail ? detailState.error : null;
  const audit = auditState.id === cameraId ? auditState.items : [];
  const auditError = auditState.id === cameraId && auditState.error;
  const health = camera ? cameraHealth(camera) : "unknown";

  return (
    <>
      <button className="drawer-scrim" aria-label="Close camera details" onClick={onClose} />
      <aside className="detail-drawer" aria-label="Camera details">
        <header className="detail-drawer__header">
          <div><span className="eyebrow">Registry asset profile</span><h2>{camera?.camera_name ?? "Camera details"}</h2>{camera ? <code>{camera.camera_code}</code> : null}</div>
          <button type="button" aria-label="Close camera details" onClick={onClose}><X aria-hidden="true" size={20} /></button>
        </header>
        {loading && !camera ? <LoadingState label="Retrieving camera profile…" /> : null}
        {error && !camera ? <ErrorState message={error} onRetry={() => setReload((value) => value + 1)} /> : null}
        {camera ? (
          <div className="detail-drawer__body">
            <section className="camera-posture">
              <div><span className={`camera-posture__icon camera-posture__icon--${health}`}><Camera aria-hidden="true" size={25} /></span><span><small>Operational health</small><StatusBadge value={health} pulse /></span></div>
              <div><small>Lifecycle</small><StatusBadge value={camera.status} kind="lifecycle" /></div>
              <p><Clock3 aria-hidden="true" size={13} /> Last heartbeat {relativeTime(camera.last_heartbeat)}</p>
            </section>

            <DetailSection title="Jurisdiction & location" icon={MapPin}>
              <dl className="detail-grid">
                <Detail label="Department" value={departmentLabel(camera)} icon={Building2} />
                <Detail label="District" value={camera.district} />
                <Detail label="City / locality" value={camera.city} />
                <Detail label="Custodian" value={camera.ownership ?? camera.owner_name} />
                <Detail label="Location" value={camera.location_description ?? camera.location} full />
                <Detail label="GIS coordinate" value={`${Number(camera.latitude).toFixed(6)}, ${Number(camera.longitude).toFixed(6)}`} full mono />
              </dl>
            </DetailSection>

            <DetailSection title="Device & federation profile" icon={Network}>
              <dl className="detail-grid">
                <Detail label="Camera type" value={titleCase(camera.camera_type)} icon={Radio} />
                <Detail label="Vendor" value={camera.vendor} />
                <Detail label="Model" value={camera.model} />
                <Detail label="Existing VMS" value={camera.vms} />
                <Detail label="Connectivity" value={titleCase(camera.connectivity_type)} />
                <Detail label="Protocol" value={titleCase(camera.stream_protocol)} />
              </dl>
              <div className="protocol-flags">
                <span className={camera.rtsp_capable ? "protocol-flag protocol-flag--yes" : "protocol-flag"}><i />RTSP {camera.rtsp_capable ? "capable" : "not declared"}</span>
                <span className={camera.onvif_capable ? "protocol-flag protocol-flag--yes" : "protocol-flag"}><i />ONVIF {camera.onvif_capable ? "capable" : "not declared"}</span>
              </div>
              <p className="security-note"><ShieldCheck aria-hidden="true" size={15} /> Stream endpoints and credentials are isolated from this operator view.</p>
            </DetailSection>

            <DetailSection title="Analytics readiness" icon={BrainCircuit}>
              {camera.ai_enabled || camera.ai_capabilities?.length ? (
                <div className="detail-capabilities">
                  {(camera.ai_capabilities ?? []).map((capability) => <span key={capability}><Activity aria-hidden="true" size={13} />{titleCase(capability)}</span>)}
                  {!camera.ai_capabilities?.length ? <span><BrainCircuit size={13} />AI processing enabled</span> : null}
                </div>
              ) : <p className="detail-empty">No AI analytics have been assigned to this camera.</p>}
            </DetailSection>

            <DetailSection title="Storage & retention" icon={Server}>
              <dl className="detail-grid">
                <Detail label="Storage architecture" value={typeof camera.storage_details?.type === "string" ? camera.storage_details.type : null} icon={Database} />
                <Detail label="Retention period" value={typeof camera.storage_details?.retention_days === "number" ? `${camera.storage_details.retention_days} days` : null} />
              </dl>
            </DetailSection>

            <DetailSection title="Registry audit trail" icon={FileClock}>
              {auditError ? <p className="detail-empty">Audit history is temporarily unavailable.</p> : audit.length ? (
                <ol className="audit-timeline">
                  {audit.slice(0, 12).map((entry) => (
                    <li key={entry.id}>
                      <i aria-hidden="true" />
                      <div><strong>{titleCase(entry.action)}</strong><span>{entry.actor_name || entry.actor_id || entry.source || "System process"}</span><small>{formatTimestamp(entry.created_at)}</small></div>
                    </li>
                  ))}
                </ol>
              ) : <p className="detail-empty">No audit events have been recorded for this camera.</p>}
            </DetailSection>

            <footer className="record-metadata">
              <span><CalendarClock aria-hidden="true" size={14} /> Created {formatTimestamp(camera.created_at)}</span>
              <span>Updated {formatTimestamp(camera.updated_at)}</span>
              <code>{camera.camera_uuid ?? camera.id}</code>
            </footer>
          </div>
        ) : null}
      </aside>
    </>
  );
}

function DetailSection({ title, icon: Icon, children }: { title: string; icon: typeof Camera; children: React.ReactNode }) {
  return <section className="detail-section"><h3><Icon aria-hidden="true" size={16} />{title}</h3>{children}</section>;
}

function Detail({ label, value, icon: Icon, full = false, mono = false }: { label: string; value?: string | null; icon?: typeof Camera; full?: boolean; mono?: boolean }) {
  return <div className={full ? "detail-grid__full" : undefined}><dt>{Icon ? <Icon aria-hidden="true" size={12} /> : null}{label}</dt><dd className={mono ? "mono" : undefined}>{value || "Not provided"}</dd></div>;
}
