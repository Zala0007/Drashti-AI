import {
  Activity,
  Camera,
  CircleOff,
  Clock3,
  Gauge,
  LoaderCircle,
  MapPin,
  OctagonAlert,
  Radio,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  TimerReset,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, federationApi } from "../lib/api";
import { formatTimestamp, relativeTime, titleCase } from "../lib/format";
import type { RuntimeCapabilities, RuntimeSession } from "../types/federation";
import { HlsVideoPlayer } from "./HlsVideoPlayer";
import { RuntimeStatusBadge } from "./RuntimeStatusBadge";

interface LiveRuntimeDrawerProps {
  sessionId: string | null;
  initialSession?: RuntimeSession | null;
  capabilities?: RuntimeCapabilities | null;
  onClose: () => void;
  onSessionChanged: (session: RuntimeSession) => void;
}

const safeMessage = (error: unknown): string => error instanceof ApiError
  ? error.message
  : "The media runtime could not complete this operation.";

const pollableStates = new Set(["starting", "live", "degraded", "backoff"]);

export function LiveRuntimeDrawer({
  sessionId,
  initialSession,
  capabilities,
  onClose,
  onSessionChanged,
}: LiveRuntimeDrawerProps) {
  const [session, setSession] = useState<RuntimeSession | null>(initialSession ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<"stop" | "restart" | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!sessionId) {
      setSession(null);
      setError(null);
      return;
    }
    setSession((current) => current?.id === sessionId ? current : initialSession?.id === sessionId ? initialSession : null);
  }, [initialSession, sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    const poll = async (showLoading: boolean) => {
      controller?.abort();
      controller = new AbortController();
      if (showLoading) setLoading(true);
      try {
        const next = await federationApi.runtimeSession(sessionId, controller.signal);
        if (cancelled) return;
        setSession(next);
        setError(null);
        onSessionChanged(next);
        if (pollableStates.has(next.state)) timer = setTimeout(() => void poll(false), 2000);
      } catch (cause) {
        if (cancelled || (cause instanceof DOMException && cause.name === "AbortError")) return;
        setError(safeMessage(cause));
        timer = setTimeout(() => void poll(false), 4000);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void poll(true);
    return () => {
      cancelled = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [onSessionChanged, reloadKey, sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape" && !action) onClose(); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [action, onClose, sessionId]);

  if (!sessionId) return null;

  const runAction = async (kind: "stop" | "restart") => {
    if (!session) return;
    setAction(kind);
    setError(null);
    try {
      const next = kind === "stop"
        ? await federationApi.stopRuntime(session.id)
        : await federationApi.restartRuntime(session.id);
      setSession(next);
      onSessionChanged(next);
      setReloadKey((value) => value + 1);
    } catch (cause) {
      setError(safeMessage(cause));
    } finally {
      setAction(null);
    }
  };

  const mediaVisible = session && ["live", "degraded"].includes(session.state);
  const active = session && ["starting", "live", "degraded", "backoff"].includes(session.state);

  return (
    <>
      <button className="drawer-scrim" aria-label="Close live media" onClick={onClose} />
      <aside className="detail-drawer runtime-drawer" aria-label="Live media runtime">
        <header className="detail-drawer__header runtime-drawer__header">
          <div><span className="eyebrow">P0.3R / Browser media delivery</span><h2>{session?.camera.camera_name ?? "Live runtime"}</h2>{session ? <code>{session.camera.camera_code} / {session.profile.name}</code> : null}</div>
          <button type="button" aria-label="Close live media" onClick={onClose} disabled={Boolean(action)}><X aria-hidden="true" size={20} /></button>
        </header>
        <div className="runtime-drawer__body">
          {loading && !session ? <div className="runtime-drawer-loading" role="status"><LoaderCircle className="spin" size={28} /><strong>Loading runtime session…</strong></div> : null}
          {error ? <div className="runtime-drawer-error" role="alert"><OctagonAlert size={18} /><span><strong>Runtime operation unavailable</strong><small>{error}</small></span><button type="button" onClick={() => setReloadKey((value) => value + 1)}><RefreshCw size={14} />Retry</button></div> : null}
          {session ? (
            <>
              <section className="runtime-drawer-posture">
                <span className="runtime-drawer-posture__icon"><Radio size={24} /></span>
                <div><small>Delivery state</small><RuntimeStatusBadge state={session.state} /></div>
                <span className="runtime-session-age"><Clock3 size={13} />{relativeTime(session.state_changed_at)}</span>
              </section>

              <section className="runtime-media-stage">
                {mediaVisible ? <HlsVideoPlayer playlistUrl={session.playlist_url} cameraName={session.camera.camera_name} /> : <RuntimePlaceholder session={session} />}
              </section>

              <div className="runtime-drawer-actions">
                {active ? <button className="button button--danger" type="button" onClick={() => void runAction("stop")} disabled={Boolean(action)}>{action === "stop" ? <LoaderCircle className="spin" size={16} /> : <CircleOff size={16} />}{action === "stop" ? "Stopping…" : "Stop runtime"}</button> : null}
                <button className="button button--secondary" type="button" onClick={() => void runAction("restart")} disabled={Boolean(action)}>{action === "restart" ? <LoaderCircle className="spin" size={16} /> : <RotateCcw size={16} />}{action === "restart" ? "Restarting…" : "Restart runtime"}</button>
              </div>

              <section className="runtime-metric-grid" aria-label="Live runtime metrics">
                <RuntimeMetric icon={Gauge} label="Output FPS" value={session.metrics.fps == null ? "—" : session.metrics.fps.toFixed(1)} />
                <RuntimeMetric icon={Activity} label="Frames processed" value={session.metrics.frame == null ? "—" : session.metrics.frame.toLocaleString("en-IN")} />
                <RuntimeMetric icon={TimerReset} label="Runtime restarts" value={session.restart_count.toLocaleString("en-IN")} />
                <RuntimeMetric icon={Clock3} label="Last progress" value={relativeTime(session.last_progress_at ?? session.metrics.progress_at)} />
              </section>

              <section className="runtime-profile-card">
                <header><Camera size={16} /><span><strong>Runtime binding</strong><small>Safe identity and supervision context</small></span></header>
                <dl>
                  <div><dt>Department</dt><dd>{session.camera.department_name || "Not provided"}</dd></div>
                  <div><dt>Location</dt><dd><MapPin size={12} />{[session.camera.city, session.camera.district].filter(Boolean).join(", ") || "Not provided"}</dd></div>
                  <div><dt>Adapter</dt><dd>{titleCase(session.profile.adapter_kind)}</dd></div>
                  <div><dt>Role</dt><dd>{titleCase(session.profile.stream_role)}</dd></div>
                  <div><dt>Started</dt><dd>{formatTimestamp(session.started_at)}</dd></div>
                  <div><dt>Playlist updated</dt><dd>{formatTimestamp(session.last_playlist_at)}</dd></div>
                </dl>
              </section>

              {session.last_error_code ? <div className="runtime-safe-error"><OctagonAlert size={16} /><span><strong>{titleCase(session.last_error_code)}</strong><small>The runtime reported a sanitized operational error. Camera source details remain hidden.</small></span></div> : null}

              <div className="runtime-ai-boundary"><ShieldCheck size={18} /><span><strong>Browser delivery is not AI inference</strong><small>This session proves supervised media delivery through a same-origin HLS playlist. ANPR, detection, watchlists, and alert generation remain separate downstream modules.</small></span></div>
              <footer className="runtime-drawer-footer"><span>Watchdog {capabilities?.supervision.watchdog_seconds ?? "—"}s</span><span>Maximum backoff {capabilities?.supervision.max_backoff_seconds ?? "—"}s</span><code>{session.id}</code></footer>
            </>
          ) : null}
        </div>
      </aside>
    </>
  );
}

function RuntimePlaceholder({ session }: { session: RuntimeSession }) {
  const copy: Record<string, { title: string; detail: string }> = {
    starting: { title: "Media process starting", detail: "The supervisor is waiting for playlist and progress evidence." },
    backoff: { title: "Supervised restart backoff", detail: "The watchdog will retry according to the bounded backoff policy." },
    stopped: { title: "Runtime stopped", detail: "No media process is active. Restart to request browser delivery again." },
    failed: { title: "Runtime failed safely", detail: "Review the sanitized error code, then restart when the source is ready." },
    unavailable: { title: "Runtime unavailable", detail: "Browser media delivery is not available for this profile or deployment." },
  };
  const content = copy[session.state] ?? { title: "No live media available", detail: "The runtime has not produced an allowlisted playlist." };
  return <div className={`runtime-placeholder runtime-placeholder--${session.state}`} role="status"><span><Radio size={28} /></span><RuntimeStatusBadge state={session.state} /><strong>{content.title}</strong><p>{content.detail}</p></div>;
}

function RuntimeMetric({ icon: Icon, label, value }: { icon: typeof Gauge; label: string; value: string }) {
  return <article><Icon size={16} /><span><small>{label}</small><strong>{value}</strong></span></article>;
}
