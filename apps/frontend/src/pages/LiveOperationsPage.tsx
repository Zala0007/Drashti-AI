import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  Camera as CameraIcon,
  ChevronLeft,
  ChevronRight,
  CircleStop,
  Clock3,
  Cpu,
  Gauge,
  Grid2X2,
  Grid3X3,
  LoaderCircle,
  MapPin,
  Maximize2,
  Play,
  Radio,
  RefreshCw,
  RotateCcw,
  ServerCog,
  Search,
  ShieldCheck,
  Signal,
  Video,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, registryApi, streamApi } from "../lib/api";
import { emptyCameraFilters } from "../lib/registryView";
import type { Camera } from "../types/registry";
import type {
  AnalyticsCapabilities,
  CameraAnalytics,
  ProcessingStreamSession,
  ProcessingStreamState,
  StreamAggregateMetrics,
  StreamCapabilities,
} from "../types/streams";

const activeStates = new Set<ProcessingStreamState>([
  "connecting",
  "connected",
  "streaming",
  "degraded",
  "reconnecting",
]);

const errorMessage = (error: unknown) =>
  error instanceof ApiError ? error.message : "The stream processing service is unavailable.";

const number = (value: number, digits = 0) =>
  value.toLocaleString("en-IN", { maximumFractionDigits: digits });

const latency = (value: number | null) => value == null ? "—" : `${number(value)} ms`;

export function LiveOperationsPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [sessions, setSessions] = useState<ProcessingStreamSession[]>([]);
  const [metrics, setMetrics] = useState<StreamAggregateMetrics | null>(null);
  const [capabilities, setCapabilities] = useState<StreamCapabilities | null>(null);
  const [analyticsCapabilities, setAnalyticsCapabilities] = useState<AnalyticsCapabilities | null>(null);
  const [analytics, setAnalytics] = useState<CameraAnalytics[]>([]);
  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);
  const [busyCameraId, setBusyCameraId] = useState<string | null>(null);
  const [columns, setColumns] = useState<2 | 3>(3);
  const [wallPage, setWallPage] = useState(1);
  const [cameraSearch, setCameraSearch] = useState("");
  const [transportPreference, setTransportPreference] = useState<"auto" | "rtsp" | "hls">("auto");
  const [bulkOperation, setBulkOperation] = useState<{
    action: "start" | "stop";
    completed: number;
    total: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const telemetryRequestActive = useRef(false);

  const refreshTelemetry = useCallback(async (signal?: AbortSignal) => {
    if (telemetryRequestActive.current) return;
    telemetryRequestActive.current = true;
    try {
      const [sessionPage, streamMetrics, analyticsPage] = await Promise.all([
        streamApi.sessions(signal),
        streamApi.metrics(signal),
        streamApi.analytics(signal).catch(() => ({ items: [], total: 0 })),
      ]);
      setSessions(sessionPage.items);
      setMetrics(streamMetrics);
      setAnalytics(Array.isArray(analyticsPage.items) ? analyticsPage.items : []);
      setError(null);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setError(errorMessage(caught));
    } finally {
      telemetryRequestActive.current = false;
    }
  }, []);

  const refresh = useCallback(async (signal?: AbortSignal, quiet = false) => {
    if (!quiet) setInitialLoading(true);
    try {
      const [cameraPage, sessionPage, streamMetrics, engineCapabilities, analyticsPage, aiCapabilities] = await Promise.all([
        registryApi.cameras(emptyCameraFilters, 1, 100, signal),
        streamApi.sessions(signal),
        streamApi.metrics(signal),
        streamApi.capabilities(signal),
        streamApi.analytics(signal).catch(() => ({ items: [], total: 0 })),
        streamApi.analyticsCapabilities(signal).catch(() => null),
      ]);
      setCameras(cameraPage.items);
      setSessions(sessionPage.items);
      setMetrics(streamMetrics);
      setCapabilities(engineCapabilities);
      setAnalytics(Array.isArray(analyticsPage.items) ? analyticsPage.items : []);
      setAnalyticsCapabilities(aiCapabilities?.status ? aiCapabilities : null);
      setError(null);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setError(errorMessage(caught));
    } finally {
      if (!quiet) setInitialLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    let timer: number | undefined;

    const schedule = () => {
      if (cancelled) return;
      timer = window.setTimeout(async () => {
        if (!document.hidden) await refreshTelemetry(controller.signal);
        schedule();
      }, document.hidden ? 10_000 : 2_000);
    };

    const handleVisibility = () => {
      if (timer) window.clearTimeout(timer);
      if (!document.hidden) {
        void refreshTelemetry(controller.signal).finally(schedule);
      } else {
        schedule();
      }
    };

    void refresh(controller.signal).finally(schedule);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      cancelled = true;
      controller.abort();
      if (timer) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [refresh, refreshTelemetry]);

  const latestSessionByCamera = useMemo(() => {
    const map = new Map<string, ProcessingStreamSession>();
    sessions.forEach((session) => {
      if (!map.has(session.camera.id)) map.set(session.camera.id, session);
    });
    return map;
  }, [sessions]);
  const analyticsByCamera = useMemo(
    () => new Map(analytics.map((item) => [item.camera_id, item])),
    [analytics],
  );

  const selectedCamera = cameras.find((camera) => camera.id === selectedCameraId) ?? null;
  const selectedSession = selectedCameraId
    ? latestSessionByCamera.get(selectedCameraId) ?? null
    : null;
  const activeCameraIds = useMemo(
    () => new Set(sessions.filter((session) => activeStates.has(session.state)).map((session) => session.camera.id)),
    [sessions],
  );

  const filteredCameras = useMemo(() => {
    const query = cameraSearch.trim().toLocaleLowerCase();
    if (!query) return cameras;
    return cameras.filter((camera) => [
      camera.camera_name,
      camera.camera_code,
      camera.district,
      camera.city,
      camera.vendor,
    ].some((value) => value?.toLocaleLowerCase().includes(query)));
  }, [cameraSearch, cameras]);

  const pageSize = columns === 3 ? 9 : 4;
  const pageCount = Math.max(1, Math.ceil(filteredCameras.length / pageSize));
  const currentPage = Math.min(wallPage, pageCount);

  useEffect(() => setWallPage(1), [cameraSearch, columns]);

  const runAction = async (cameraId: string, action: "start" | "stop" | "restart") => {
    setBusyCameraId(cameraId);
    setError(null);
    try {
      const preference = transportPreference === "auto"
        ? {}
        : { preferred_adapter: transportPreference };
      const updated = action === "stop"
        ? await streamApi.stop(cameraId)
        : action === "restart"
          ? await streamApi.restart(cameraId, preference)
          : await streamApi.start(cameraId, preference);
      setSessions((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
      await refreshTelemetry();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusyCameraId(null);
    }
  };

  const runBulkAction = async (action: "start" | "stop") => {
    const visibleCameraIds = new Set(displayed.map((camera) => camera.id));
    const targets = cameras.filter((camera) => (
      action === "start" ? !activeCameraIds.has(camera.id) : activeCameraIds.has(camera.id)
    )).sort((left, right) => Number(visibleCameraIds.has(right.id)) - Number(visibleCameraIds.has(left.id)));
    if (!targets.length) return;

    setBulkOperation({ action, completed: 0, total: targets.length });
    setError(null);
    let completed = 0;
    let failures = 0;
    const preference = transportPreference === "auto"
      ? {}
      : { preferred_adapter: transportPreference };

    if (action === "start") {
      let cursor = 0;
      const startWorker = async () => {
        while (cursor < targets.length) {
          const camera = targets[cursor];
          cursor += 1;
          const controller = new AbortController();
          const timeout = window.setTimeout(() => controller.abort(), 15_000);
          try {
            const updated = await streamApi.start(camera.id, preference, controller.signal);
            setSessions((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
          } catch {
            failures += 1;
          } finally {
            window.clearTimeout(timeout);
            completed += 1;
            setBulkOperation({ action, completed, total: targets.length });
          }
        }
      };
      await Promise.all(
        Array.from({ length: Math.min(3, targets.length) }, () => startWorker()),
      );
    } else {
      for (let index = 0; index < targets.length; index += 4) {
        const batch = targets.slice(index, index + 4);
        const results = await Promise.allSettled(batch.map((camera) => streamApi.stop(camera.id)));
        results.forEach((result) => {
          if (result.status === "fulfilled") {
            const updated = result.value;
            setSessions((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
          } else {
            failures += 1;
          }
        });
        completed += batch.length;
        setBulkOperation({ action, completed, total: targets.length });
      }
    }

    await refreshTelemetry();
    if (failures) {
      setError(`${failures} of ${targets.length} stream operations failed. Healthy cameras were not interrupted.`);
    }
    setBulkOperation(null);
  };

  const displayed = filteredCameras.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );
  const liveSessionCount = sessions.filter((session) => session.state === "streaming").length;
  const recoveryCount = sessions.filter((session) => ["degraded", "reconnecting"].includes(session.state)).length;
  const visiblePreviewCount = displayed.filter((camera) => {
    const session = latestSessionByCamera.get(camera.id);
    return session ? activeStates.has(session.state) : false;
  }).length;

  return (
    <section className="live-ops">
      <header className="live-ops__hero">
        <div>
          <span className="section-eyebrow"><Radio size={14} /> P04 · Video stream processing</span>
          <h1>Live Operations Matrix</h1>
          <p>Latest-frame-first monitoring, decoder supervision and AI-ready batch dispatch across federated cameras.</p>
        </div>
        <div className="live-ops__hero-actions">
          <button
            className="live-bulk-action live-bulk-action--start"
            type="button"
            disabled={Boolean(bulkOperation) || activeCameraIds.size === cameras.length || !cameras.length}
            onClick={() => void runBulkAction("start")}
          >
            {bulkOperation?.action === "start" ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />}
            {bulkOperation?.action === "start"
              ? `Starting ${bulkOperation.completed}/${bulkOperation.total}`
              : `Start grid (${cameras.length - activeCameraIds.size})`}
          </button>
          <button
            className="live-bulk-action live-bulk-action--stop"
            type="button"
            disabled={Boolean(bulkOperation) || activeCameraIds.size === 0}
            onClick={() => void runBulkAction("stop")}
          >
            {bulkOperation?.action === "stop" ? <LoaderCircle className="spin" size={15} /> : <CircleStop size={15} />}
            {bulkOperation?.action === "stop"
              ? `Stopping ${bulkOperation.completed}/${bulkOperation.total}`
              : `Stop active (${activeCameraIds.size})`}
          </button>
          <span className={`engine-posture${capabilities?.available ? " engine-posture--ready" : ""}`}>
            <ServerCog size={16} />
            <span><small>Decoder node</small><strong>{capabilities?.available ? (capabilities.hardware_decode_active ? "NVDEC active" : "FFmpeg ready") : "Unavailable"}</strong></span>
          </span>
          <button className="icon-button" type="button" aria-label="Refresh live operations" onClick={() => void refresh()}>
            <RefreshCw size={17} />
          </button>
        </div>
      </header>

      {error ? <div className="live-ops__error" role="alert"><AlertTriangle size={17} />{error}</div> : null}

      <div className="stream-kpis" aria-label="Processing engine metrics">
        <StreamKpi icon={Video} label="Active streams" value={number(metrics?.active_streams ?? 0)} detail={`${capabilities?.max_active_sessions ?? 32} node capacity`} tone="cyan" />
        <StreamKpi icon={Gauge} label="Decoded throughput" value={`${number(metrics?.average_decoded_fps ?? 0, 1)} FPS`} detail="Average per active feed" />
        <StreamKpi icon={Clock3} label="Frame latency" value={`${number(metrics?.average_latency_ms ?? 0)} ms`} detail="Receive-to-dispatch estimate" tone={(metrics?.average_latency_ms ?? 0) > 750 ? "amber" : "green"} />
        <StreamKpi icon={Activity} label="Dropped frames" value={number(metrics?.total_frames_dropped ?? 0)} detail="Bounded latency protection" />
        <StreamKpi icon={RotateCcw} label="Reconnects" value={number(metrics?.total_reconnects ?? 0)} detail={`${metrics?.reconnecting_streams ?? 0} reconnecting now`} tone={(metrics?.reconnecting_streams ?? 0) ? "amber" : undefined} />
        <StreamKpi icon={BrainCircuit} label="AI inference" value={analyticsCapabilities?.status ?? `${metrics?.scheduler_queue_depth ?? 0} queued`} detail={analyticsCapabilities?.device ? `${analyticsCapabilities.device} · ${analytics.length} cameras reported` : analyticsCapabilities?.reason ?? (metrics?.ai_consumer_attached ? "Inference consumer attached" : "P05 consumer interface ready")} tone="violet" />
      </div>

      <section className="live-assurance" aria-label="Live wall delivery policy">
        <div className="live-assurance__title"><Signal size={17} /><span><small>Live wall assurance</small><strong>Continuous, latest-frame delivery</strong></span></div>
        <div><i className="live-assurance__pulse" /><span><small>Delivery</small><strong>{liveSessionCount} live · {visiblePreviewCount} visible previews</strong></span></div>
        <div><RotateCcw size={16} /><span><small>Recovery</small><strong>{recoveryCount ? `${recoveryCount} auto-recovering` : "Watchdogs armed"}</strong></span></div>
        <div><Activity size={16} /><span><small>Latency policy</small><strong>{capabilities?.latest_frame_semantics ? "Newest frame wins" : "Awaiting engine"}</strong></span></div>
        <div><ShieldCheck size={16} /><span><small>Load policy</small><strong>Visible-first · connection-safe snapshots</strong></span></div>
      </section>

      <div className="live-workspace">
        <section className="video-wall">
          <header className="video-wall__toolbar">
            <div><strong>Camera wall</strong><small>{filteredCameras.length} matched · {cameras.length} registered cameras</small></div>
            <div className="video-wall__controls">
              <label className="wall-search">
                <Search size={14} />
                <input value={cameraSearch} onChange={(event) => setCameraSearch(event.target.value)} placeholder="Find camera, code or district" aria-label="Search live cameras" />
              </label>
              <label className="wall-transport">
                <Signal size={14} />
                <select aria-label="Preferred stream transport" value={transportPreference} onChange={(event) => setTransportPreference(event.target.value as "auto" | "rtsp" | "hls")}>
                  <option value="hls">HLS · restricted network</option>
                  <option value="auto">Adaptive · RTSP then HLS</option>
                  <option value="rtsp">RTSP/TCP · edge AI</option>
                </select>
              </label>
              <div className="wall-pagination" aria-label="Camera wall pages">
                <button type="button" disabled={currentPage === 1} onClick={() => setWallPage((page) => Math.max(1, page - 1))} aria-label="Previous camera page"><ChevronLeft size={15} /></button>
                <span>{currentPage} / {pageCount}</span>
                <button type="button" disabled={currentPage === pageCount} onClick={() => setWallPage((page) => Math.min(pageCount, page + 1))} aria-label="Next camera page"><ChevronRight size={15} /></button>
              </div>
              <div className="wall-layout-switch" aria-label="Video wall layout">
                <button className={columns === 2 ? "is-active" : ""} type="button" onClick={() => setColumns(2)} aria-label="2 by 2 layout"><Grid2X2 size={16} /></button>
                <button className={columns === 3 ? "is-active" : ""} type="button" onClick={() => setColumns(3)} aria-label="3 by 3 layout"><Grid3X3 size={16} /></button>
              </div>
            </div>
          </header>

          {initialLoading ? <div className="video-wall__empty"><RefreshCw className="spin" size={22} />Loading stream inventory…</div> : null}
          {!initialLoading && displayed.length === 0 ? (
            <div className="video-wall__empty">
              <CameraIcon size={24} />
              {cameras.length
                ? "No camera matches the current wall search."
                : "Onboard cameras in P01 before starting streams."}
            </div>
          ) : null}
          <div className={`video-grid video-grid--${columns}`}>
            {displayed.map((camera) => {
              const session = latestSessionByCamera.get(camera.id);
              const cameraAnalytics = analyticsByCamera.get(camera.id);
              const active = session ? activeStates.has(session.state) : false;
              return (
                <article
                  key={camera.id}
                  className={`feed-tile${selectedCameraId === camera.id ? " feed-tile--selected" : ""}${session && ["degraded", "reconnecting"].includes(session.state) ? " feed-tile--recovering" : ""}`}
                  onClick={() => setSelectedCameraId(camera.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedCameraId(camera.id);
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  aria-label={`Inspect ${camera.camera_name}`}
                >
                  <div className="feed-tile__viewport">
                    {active && session ? (
                      <StreamPreview
                        session={session}
                        cameraName={camera.camera_name}
                        analytics={cameraAnalytics}
                      />
                    ) : (
                      <div className="feed-placeholder"><CameraIcon size={28} /><span>{session?.state === "failed" ? "Decoder failed" : "Stream not started"}</span></div>
                    )}
                    <div className="feed-tile__topline">
                      <StreamState state={session?.state ?? "stopped"} />
                      <span>{session?.metrics.resolution ?? "—"}</span>
                    </div>
                    <AnalyticsState active={active} capabilities={analyticsCapabilities} result={cameraAnalytics} />
                    <button className="feed-expand" type="button" aria-label={`Open ${camera.camera_name} details`}><Maximize2 size={15} /></button>
                  </div>
                  <footer>
                    <div><strong>{camera.camera_name}</strong><small><MapPin size={11} />{camera.city ?? camera.district} · {camera.camera_code}</small></div>
                    <div className="feed-live-metrics"><span>{number(session?.metrics.decoded_fps ?? 0, 1)} fps</span><span>{latency(session?.metrics.current_frame_age_ms ?? null)}</span></div>
                  </footer>
                </article>
              );
            })}
          </div>
        </section>

        <aside className={`camera-inspector${selectedCamera ? " camera-inspector--open" : ""}`}>
          {selectedCamera ? (
            <>
              <header>
                <div><span>Camera intelligence</span><strong>{selectedCamera.camera_name}</strong><small>{selectedCamera.camera_code}</small></div>
                <button type="button" aria-label="Close camera details" onClick={() => setSelectedCameraId(null)}><X size={17} /></button>
              </header>
              <section className="inspector-actions">
                <StreamState state={selectedSession?.state ?? "stopped"} />
                {selectedSession && activeStates.has(selectedSession.state) ? (
                  <>
                    <button type="button" disabled={busyCameraId === selectedCamera.id} onClick={() => void runAction(selectedCamera.id, "restart")}><RotateCcw size={14} />Restart</button>
                    <button className="is-danger" type="button" disabled={busyCameraId === selectedCamera.id} onClick={() => void runAction(selectedCamera.id, "stop")}><CircleStop size={14} />Stop</button>
                  </>
                ) : (
                  <button className="is-primary" type="button" disabled={busyCameraId === selectedCamera.id} onClick={() => void runAction(selectedCamera.id, "start")}><Play size={14} />Start processing</button>
                )}
              </section>

              <InspectorSection title="Processing telemetry" icon={Cpu}>
                <dl className="telemetry-grid">
                  <Metric label="Decoded" value={`${number(selectedSession?.metrics.decoded_fps ?? 0, 1)} fps`} />
                  <Metric label="Source timing" value={selectedSession?.metrics.pts_timing_active ? `PTS ${number(selectedSession.metrics.latest_source_pts_seconds ?? 0, 2)}s` : "Arrival fallback"} />
                  <Metric label="AI dispatch" value={`${number(selectedSession?.metrics.processing_fps ?? 0, 1)} fps`} />
                  <Metric label="Frame age" value={latency(selectedSession?.metrics.current_frame_age_ms ?? null)} />
                  <Metric label="Queue" value={`${selectedSession?.metrics.queue_depth ?? 0} / ${selectedSession?.buffer_capacity ?? 2}`} />
                  <Metric label="Received" value={number(selectedSession?.metrics.frames_received ?? 0)} />
                  <Metric label="Dropped" value={number(selectedSession?.metrics.frames_dropped ?? 0)} />
                  <Metric label="Reconnects" value={number(selectedSession?.metrics.reconnect_count ?? 0)} />
                  <Metric label="Transport failovers" value={number(selectedSession?.metrics.source_failover_count ?? 0)} />
                  <Metric label="Decoder errors" value={number(selectedSession?.metrics.decoder_errors ?? 0)} />
                </dl>
              </InspectorSection>

              <InspectorSection title="Camera & location" icon={MapPin}>
                <dl className="camera-facts">
                  <Fact label="Department" value={selectedCamera.department?.name ?? selectedCamera.department_name ?? "—"} />
                  <Fact label="District / city" value={`${selectedCamera.district} / ${selectedCamera.city ?? "—"}`} />
                  <Fact label="Coordinates" value={`${selectedCamera.latitude.toFixed(5)}, ${selectedCamera.longitude.toFixed(5)}`} />
                  <Fact label="Hardware" value={[selectedCamera.vendor, selectedCamera.model].filter(Boolean).join(" · ") || "Not recorded"} />
                  <Fact label="VMS" value={selectedCamera.vms ?? "Direct camera profile"} />
                  <Fact label="Connection" value={selectedSession ? `${selectedSession.profile.adapter_kind.toUpperCase()} · ${selectedSession.transport.toUpperCase()}` : selectedCamera.stream_protocol.toUpperCase()} />
                </dl>
              </InspectorSection>

              <InspectorSection title="AI processing contract" icon={BrainCircuit}>
                <div className="ai-contract">
                  <span><ShieldCheck size={17} /></span>
                  <div><strong>{analyticsByCamera.get(selectedCamera.id) ? "Per-camera inference active" : "P04 frame bus ready"}</strong><p>{analyticsByCamera.get(selectedCamera.id) ? `${analyticsByCamera.get(selectedCamera.id)?.detections.length ?? 0} current detections routed to ${(analyticsByCamera.get(selectedCamera.id)?.routed_modules ?? []).join(", ")}.` : analyticsCapabilities?.reason ?? "The fair scheduler will process this camera as soon as its first fresh frame arrives."}</p></div>
                </div>
                <div className="ai-capability-list">
                  {(selectedCamera.ai_capabilities.length ? selectedCamera.ai_capabilities : ["vehicle_detection", "anpr"]).map((capability) => <span key={capability}>{capability.replaceAll("_", " ")}</span>)}
                </div>
              </InspectorSection>

              {selectedSession?.last_error_message ? <div className="stream-diagnostic"><AlertTriangle size={16} /><div><strong>{selectedSession.last_error_code}</strong><p>{selectedSession.last_error_message}</p></div></div> : null}
            </>
          ) : (
            <div className="camera-inspector__empty"><Signal size={26} /><strong>Select a camera</strong><p>Open any tile to inspect its registry identity, decoder lifecycle, live health, failure details and AI handoff metrics.</p></div>
          )}
        </aside>
      </div>
    </section>
  );
}

type PreviewState = "connecting" | "live" | "recovering" | "paused";

function StreamPreview({
  session,
  cameraName,
  analytics,
}: {
  session: ProcessingStreamSession;
  cameraName: string;
  analytics?: CameraAnalytics;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const refreshTimer = useRef<number | undefined>(undefined);
  const lastReloadAt = useRef(0);
  const [revision, setRevision] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [intersecting, setIntersecting] = useState(true);
  const [pageVisible, setPageVisible] = useState(() => !document.hidden);
  const [previewState, setPreviewState] = useState<PreviewState>("connecting");

  const refreshPhase = useMemo(
    () => Array.from(session.camera.id).reduce((total, character) => total + character.charCodeAt(0), 0) % 140,
    [session.camera.id],
  );

  const requestNextFrame = useCallback((delay = 0, markConnecting = false) => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => {
      lastReloadAt.current = Date.now();
      setRevision((value) => value + 1);
      if (markConnecting) setPreviewState("connecting");
    }, delay);
  }, []);

  useEffect(() => {
    setAttempt(0);
    setPreviewState("connecting");
    requestNextFrame();
  }, [session.id, requestNextFrame]);

  useEffect(() => {
    const node = rootRef.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => setIntersecting(entry.isIntersecting),
      { rootMargin: "180px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const handleVisibility = () => setPageVisible(!document.hidden);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

  useEffect(() => {
    if (!intersecting || !pageVisible) {
      if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
      setPreviewState("paused");
      return;
    }
    if (previewState === "paused") {
      setPreviewState("connecting");
      requestNextFrame();
    }
    if (session.metrics.last_frame_at) {
      setPreviewState("live");
      setAttempt(0);
    }
  }, [intersecting, pageVisible, previewState, requestNextFrame, session.metrics.last_frame_at]);

  useEffect(() => () => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
  }, []);

  useEffect(() => {
    const frameAge = session.metrics.current_frame_age_ms;
    const staleAfter = Math.max(session.max_frame_age_ms * 3, 3_000);
    if (
      frameAge != null
      && frameAge > staleAfter
      && intersecting
      && pageVisible
      && Date.now() - lastReloadAt.current > staleAfter
    ) {
      setPreviewState("recovering");
      requestNextFrame(200, true);
    }
  }, [intersecting, pageVisible, requestNextFrame, session.max_frame_age_ms, session.metrics.current_frame_age_ms]);

  const handleError = () => {
    const nextAttempt = attempt + 1;
    setAttempt(nextAttempt);
    setPreviewState("recovering");
    const warmingUp = nextAttempt <= 20 && ["connecting", "connected", "reconnecting"].includes(session.state);
    requestNextFrame(
      warmingUp ? 280 + refreshPhase : Math.min(350 * (2 ** Math.min(nextAttempt - 1, 3)), 3_000),
      true,
    );
  };

  const shouldRender = intersecting && pageVisible;
  const stateCopy: Record<PreviewState, string> = {
    connecting: "Grabbing latest preview",
    live: "Live preview",
    recovering: `Recovering preview${attempt ? ` · attempt ${attempt}` : ""}`,
    paused: "Preview paused off-screen",
  };

  return (
    <div ref={rootRef} className={`stream-preview stream-preview--${previewState}`}>
      {shouldRender ? (
        <img
          src={streamApi.previewUrl(session.camera.id, `${session.id}-${revision}`)}
          alt={`Continuous live feed from ${cameraName}`}
          decoding="async"
          onLoad={() => {
            setAttempt(0);
            setPreviewState("live");
            requestNextFrame(280 + refreshPhase);
          }}
          onError={handleError}
        />
      ) : null}
      {previewState === "live" && analytics?.stream_id === session.id ? (
        <svg className="stream-preview__analytics" viewBox={`0 0 ${session.width} ${session.height}`} preserveAspectRatio="xMidYMid meet" aria-label={`${analytics.detections.length} AI detections`}>
          {analytics.detections.map((detection, index) => (
            <g key={`${analytics.frame_number}-${index}`} className={`analytics-box analytics-box--${detection.kind}`}>
              <rect x={detection.x1} y={detection.y1} width={Math.max(1, detection.x2 - detection.x1)} height={Math.max(1, detection.y2 - detection.y1)} />
              <text x={detection.x1 + 3} y={Math.max(13, detection.y1 - 4)}>{detection.plate_text || `${detection.class_name} ${Math.round(detection.confidence * 100)}%`}</text>
            </g>
          ))}
        </svg>
      ) : null}
      {previewState !== "live" ? (
        <span className="stream-preview__recovery" role="status">
          {previewState === "paused" ? <ShieldCheck size={17} /> : <LoaderCircle className="spin" size={17} />}
          {stateCopy[previewState]}
        </span>
      ) : null}
    </div>
  );
}

function AnalyticsState({ active, capabilities, result }: { active: boolean; capabilities: AnalyticsCapabilities | null; result?: CameraAnalytics }) {
  let label = "AI waiting for stream";
  let state = "waiting";
  if (active && capabilities?.status === "unavailable") {
    label = "AI unavailable";
    state = "error";
  } else if (active && result) {
    label = `AI active · ${result.detections.length} detected`;
    state = "active";
  } else if (active) {
    label = capabilities?.status === "initializing" ? "AI model initializing" : "AI sampling camera";
    state = "sampling";
  }
  return <div className={`ai-overlay-state ai-overlay-state--${state}`} title={capabilities?.reason ?? undefined}><BrainCircuit size={13} />{label}</div>;
}

function StreamKpi({ icon: Icon, label, value, detail, tone }: { icon: typeof Video; label: string; value: string; detail: string; tone?: "cyan" | "green" | "amber" | "violet" }) {
  return <article className={`stream-kpi${tone ? ` stream-kpi--${tone}` : ""}`}><span><Icon size={18} /></span><div><small>{label}</small><strong>{value}</strong><em>{detail}</em></div></article>;
}

function StreamState({ state }: { state: ProcessingStreamState }) {
  return <span className={`processing-state processing-state--${state}`}><i />{state}</span>;
}

function InspectorSection({ title, icon: Icon, children }: { title: string; icon: typeof Cpu; children: ReactNode }) {
  return <section className="inspector-section"><header><Icon size={15} /><strong>{title}</strong></header>{children}</section>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}
