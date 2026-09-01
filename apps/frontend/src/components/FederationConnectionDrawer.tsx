import {
  Activity,
  Boxes,
  CalendarClock,
  Camera,
  CheckCircle2,
  CircleOff,
  Clock3,
  FileClock,
  Fingerprint,
  KeyRound,
  MapPin,
  Network,
  Radar,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, federationApi } from "../lib/api";
import { connectionLocation, safeEndpointDisplay, safeMetadata } from "../lib/federation";
import { formatTimestamp, relativeTime, titleCase } from "../lib/format";
import type { FederationAdapter, FederationAuditEntry, FederationConnection, RuntimeSession } from "../types/federation";
import { ErrorState, LoadingState } from "./Feedback";
import { FederationStatusBadge } from "./FederationStatusBadge";
import { RuntimeStatusBadge } from "./RuntimeStatusBadge";

interface FederationConnectionDrawerProps {
  connectionId: string | null;
  initialConnection?: FederationConnection;
  runtimeSession?: RuntimeSession;
  adapter?: FederationAdapter;
  onClose: () => void;
  onChanged: (connection: FederationConnection) => void;
}

const messageFor = (error: unknown): string => error instanceof ApiError
  ? error.message
  : "The connection profile could not be loaded.";

export function FederationConnectionDrawer({ connectionId, initialConnection, runtimeSession, adapter, onClose, onChanged }: FederationConnectionDrawerProps) {
  const [connection, setConnection] = useState<FederationConnection | null>(null);
  const [audit, setAudit] = useState<FederationAuditEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [auditUnavailable, setAuditUnavailable] = useState(false);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!connectionId) {
      setConnection(null);
      setAudit([]);
      return;
    }
    const controller = new AbortController();
    const cachedConnection = initialConnection?.id === connectionId ? initialConnection : null;
    setConnection((current) => cachedConnection ?? (current?.id === connectionId ? current : null));
    setAudit([]);
    setLoading(true);
    setError(null);
    setAuditUnavailable(false);
    setProbeError(null);
    federationApi.connection(connectionId, controller.signal)
      .then((detail) => {
        if (!controller.signal.aborted) setConnection(detail);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(messageFor(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    federationApi.audit(connectionId, controller.signal)
      .then((entries) => {
        if (!controller.signal.aborted) setAudit(entries);
      })
      .catch(() => {
        if (!controller.signal.aborted) setAuditUnavailable(true);
      });
    return () => controller.abort();
  }, [connectionId, initialConnection, reload]);

  useEffect(() => {
    if (!connectionId) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape" && !probing) onClose(); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [connectionId, onClose, probing]);

  if (!connectionId) return null;

  const probe = async () => {
    if (!connection) return;
    setProbing(true);
    setProbeError(null);
    try {
      const updated = await federationApi.probe(connection.id);
      setConnection(updated);
      onChanged(updated);
      setReload((value) => value + 1);
    } catch (cause) {
      setProbeError(messageFor(cause));
    } finally {
      setProbing(false);
    }
  };

  const metadata = safeMetadata(connection?.normalized_metadata);

  return (
    <>
      <button className="drawer-scrim" aria-label="Close connection details" onClick={onClose} />
      <aside className="detail-drawer federation-drawer" aria-label="Connection details" aria-busy={loading}>
        <header className="detail-drawer__header federation-drawer__header">
          <div><span className="eyebrow">Encrypted federation profile</span><h2>{connection?.name ?? "Connection details"}</h2>{connection ? <code>{connection.camera_code} / {connection.adapter_kind}</code> : null}</div>
          <button type="button" aria-label="Close connection details" onClick={onClose} disabled={probing}><X aria-hidden="true" size={20} /></button>
        </header>
        {loading && !connection ? <LoadingState label="Retrieving secure profile…" /> : null}
        {error && !connection ? <ErrorState message={error} onRetry={() => setReload((value) => value + 1)} /> : null}
        {connection ? (
          <div className="detail-drawer__body">
            {loading ? <div className="connection-refresh-state"><span aria-hidden="true" />Refreshing authoritative camera details</div> : null}
            {error ? <div className="drawer-inline-error" role="status"><Activity size={16} /><span>{error} Showing the latest profile already loaded from the federation list.</span><button type="button" onClick={() => setReload((value) => value + 1)}>Retry</button></div> : null}
            <section className="federation-camera-identity">
              <span className="federation-camera-identity__glyph"><Camera aria-hidden="true" size={23} /></span>
              <div><small>Federated camera asset</small><h3>{connection.camera_name}</h3><code>{connection.camera_code}</code></div>
              {runtimeSession ? <RuntimeStatusBadge state={runtimeSession.state} /> : <span className="runtime-status runtime-status--stopped">No live runtime</span>}
              <footer><span><ShieldCheck size={13} />{connection.department_name || "Department unavailable"}</span><span><MapPin size={13} />{connectionLocation(connection)}</span></footer>
            </section>
            <section className="federation-profile-posture">
              <span className="federation-profile-posture__icon"><Network size={25} /></span>
              <div><small>Verification posture</small><FederationStatusBadge value={connection.verification_status} /></div>
              <span className={`activation-pill${connection.enabled ? " activation-pill--enabled" : ""}`}>{connection.enabled ? <CheckCircle2 size={13} /> : <CircleOff size={13} />}{connection.enabled ? "Enabled" : "Disabled"}</span>
              <p><Clock3 size={13} /> Last probe {relativeTime(connection.last_probe_at)}</p>
            </section>

            {probeError ? <div className="drawer-inline-error" role="alert"><Activity size={16} /><span>{probeError}</span></div> : null}
            <button className="button button--primary federation-drawer__probe" type="button" onClick={probe} disabled={probing || adapter?.probe_supported === false}>
              <Radar className={probing ? "spin" : undefined} size={16} />{probing ? "Running secure probe…" : adapter?.probe_supported === false ? "Probe unsupported by adapter" : "Run secure capability probe"}
            </button>

            <DrawerSection title="Registry binding" icon={Camera}>
              <dl className="detail-grid">
                <DrawerDetail label="Camera" value={connection.camera_name} />
                <DrawerDetail label="Camera code" value={connection.camera_code} mono />
                <DrawerDetail label="Department" value={connection.department_name} />
                <DrawerDetail label="Jurisdiction" value={connectionLocation(connection)} icon={MapPin} />
              </dl>
            </DrawerSection>

            <DrawerSection title="Adapter & routing" icon={Boxes}>
              <dl className="detail-grid">
                <DrawerDetail label="Adapter" value={connection.adapter_label || titleCase(connection.adapter_kind)} />
                <DrawerDetail label="Stream role" value={titleCase(connection.stream_role)} />
                <DrawerDetail label="Priority" value={String(connection.priority)} />
                <DrawerDetail label="Probe latency" value={connection.last_probe_latency_ms == null ? "Not measured" : `${Math.round(connection.last_probe_latency_ms)} ms`} />
                <DrawerDetail label="Redacted endpoint" value={safeEndpointDisplay(connection.endpoint_display)} full mono />
              </dl>
              <div className="connection-security-flags">
                <span><ShieldCheck size={14} />Endpoint encrypted</span>
                <span><KeyRound size={14} />{connection.has_credential_reference ? "Credential reference attached" : "No credential reference"}</span>
              </div>
            </DrawerSection>

            <DrawerSection title="Verification evidence" icon={Radar}>
              <dl className="detail-grid">
                <DrawerDetail label="Last probe" value={formatTimestamp(connection.last_probe_at)} />
                <DrawerDetail label="Last success" value={formatTimestamp(connection.last_success_at)} />
                <DrawerDetail label="Failure count" value={String(connection.failure_count ?? 0)} />
                <DrawerDetail label="Last error code" value={connection.last_error_code || "None"} />
              </dl>
              {connection.last_error_message ? <p className="safe-error-summary">The adapter reported a safe operational error. Use the error code and audit trail for diagnosis; source details remain redacted.</p> : null}
            </DrawerSection>

            <DrawerSection title="Normalized probe metadata" icon={Fingerprint}>
              {metadata.length ? <dl className="metadata-grid">{metadata.map(([key, value]) => <div key={key}><dt>{titleCase(key)}</dt><dd>{value}</dd></div>)}</dl> : <p className="detail-empty">No normalized adapter metadata is available until a successful probe.</p>}
            </DrawerSection>

            <DrawerSection title="State history" icon={FileClock}>
              {auditUnavailable ? <p className="detail-empty">Connection audit history is temporarily unavailable.</p> : audit.length ? (
                <ol className="audit-timeline">
                  {audit.slice(0, 16).map((entry) => <li key={entry.id}><i aria-hidden="true" /><div><strong>{titleCase(entry.action)}</strong><span>{entry.actor_name || entry.actor_id || entry.source || "Platform service"}</span><small>{formatTimestamp(entry.created_at)}</small></div></li>)}
                </ol>
              ) : <p className="detail-empty">No connection state changes have been recorded.</p>}
            </DrawerSection>

            <footer className="record-metadata">
              <span><CalendarClock size={14} /> Created {formatTimestamp(connection.created_at)}</span>
              <span>Updated {formatTimestamp(connection.updated_at)}</span>
              <code>{connection.id}</code>
            </footer>
          </div>
        ) : null}
      </aside>
    </>
  );
}

function DrawerSection({ title, icon: Icon, children }: { title: string; icon: typeof Network; children: React.ReactNode }) {
  return <section className="detail-section"><h3><Icon aria-hidden="true" size={16} />{title}</h3>{children}</section>;
}

function DrawerDetail({ label, value, icon: Icon, full = false, mono = false }: { label: string; value?: string | null; icon?: typeof Network; full?: boolean; mono?: boolean }) {
  return <div className={full ? "detail-grid__full" : undefined}><dt>{Icon ? <Icon size={12} /> : null}{label}</dt><dd className={mono ? "mono" : undefined}>{value || "Not provided"}</dd></div>;
}
