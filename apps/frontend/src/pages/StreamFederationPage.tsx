import {
  Activity,
  ArrowRight,
  Boxes,
  Cable,
  CloudDownload,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  CircleOff,
  Cpu,
  DatabaseZap,
  Filter,
  KeyRound,
  Layers3,
  LoaderCircle,
  Network,
  OctagonAlert,
  Play,
  Plus,
  Radar,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Square,
  Unplug,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { FederationConnectionDrawer } from "../components/FederationConnectionDrawer";
import { FederationOnboardingModal } from "../components/FederationOnboardingModal";
import { GovernmentFeedSyncModal } from "../components/GovernmentFeedSyncModal";
import { CredentialVaultModal } from "../components/CredentialVaultModal";
import { FederationStatusBadge } from "../components/FederationStatusBadge";
import { LiveRuntimeDrawer } from "../components/LiveRuntimeDrawer";
import { Modal } from "../components/Modal";
import { RuntimeStatusBadge } from "../components/RuntimeStatusBadge";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { ApiError, federationApi } from "../lib/api";
import { adapterIsAvailable, connectionLocation, federationStatusTone, safeEndpointDisplay } from "../lib/federation";
import { formatTimestamp, relativeTime, titleCase } from "../lib/format";
import type {
  FederationAdapter,
  FederationConnection,
  FederationConnectionFilters,
  FederationStatistics,
  RuntimeCapabilities,
  RuntimeSession,
} from "../types/federation";

interface StreamFederationPageProps {
  overviewStatistics?: FederationStatistics | null;
  onStatisticsChanged?: (statistics: FederationStatistics) => void;
}

const emptyFilters: FederationConnectionFilters = {
  search: "",
  camera_id: "",
  adapter_kind: "",
  verification_status: "",
  enabled: "",
};

const pageSize = 20;

const safeMessage = (error: unknown): string => error instanceof ApiError
  ? error.message
  : "The federation control plane could not complete this operation.";

export function StreamFederationPage({ overviewStatistics, onStatisticsChanged }: StreamFederationPageProps) {
  const [adapters, setAdapters] = useState<FederationAdapter[]>([]);
  const [statistics, setStatistics] = useState<FederationStatistics | null>(overviewStatistics ?? null);
  const [connections, setConnections] = useState<FederationConnection[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<FederationConnectionFilters>(emptyFilters);
  const debouncedSearch = useDebouncedValue(filters.search, 280);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [listLoading, setListLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [governmentFeedOpen, setGovernmentFeedOpen] = useState(false);
  const [credentialVaultOpen, setCredentialVaultOpen] = useState(false);
  const [credentialRefreshKey, setCredentialRefreshKey] = useState(0);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<{ connection: FederationConnection; action: "enable" | "disable" } | null>(null);
  const [runtimeCapabilities, setRuntimeCapabilities] = useState<RuntimeCapabilities | null>(null);
  const [runtimeSessions, setRuntimeSessions] = useState<RuntimeSession[]>([]);
  const [runtimeLoading, setRuntimeLoading] = useState(true);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [runtimeRefreshKey, setRuntimeRefreshKey] = useState(0);
  const [runtimeBusy, setRuntimeBusy] = useState<string | null>(null);
  const [selectedRuntimeSessionId, setSelectedRuntimeSessionId] = useState<string | null>(null);

  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);
  const refreshRuntime = useCallback(() => setRuntimeRefreshKey((value) => value + 1), []);

  const upsertRuntimeSession = useCallback((updated: RuntimeSession) => {
    setRuntimeSessions((current) => {
      const exists = current.some((item) => item.id === updated.id);
      return exists ? current.map((item) => item.id === updated.id ? updated : item) : [updated, ...current];
    });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setCatalogLoading(true);
    setCatalogError(null);
    Promise.allSettled([
      federationApi.adapters(controller.signal),
      federationApi.statistics(controller.signal),
    ]).then(([adapterResult, statisticResult]) => {
      if (controller.signal.aborted) return;
      if (adapterResult.status === "fulfilled") setAdapters(adapterResult.value);
      else setCatalogError(safeMessage(adapterResult.reason));
      if (statisticResult.status === "fulfilled") {
        setStatistics(statisticResult.value);
        onStatisticsChanged?.(statisticResult.value);
      } else if (adapterResult.status === "rejected") {
        setCatalogError(safeMessage(statisticResult.reason));
      }
      setCatalogLoading(false);
    });
    return () => controller.abort();
  }, [onStatisticsChanged, refreshKey]);

  useEffect(() => {
    const controller = new AbortController();
    setListLoading(true);
    setListError(null);
    federationApi.connections({
      search: debouncedSearch,
      camera_id: filters.camera_id,
      adapter_kind: filters.adapter_kind,
      verification_status: filters.verification_status,
      enabled: filters.enabled,
    }, page, pageSize, controller.signal)
      .then((result) => {
        setConnections(result.items);
        setTotal(result.total);
        setPages(result.pages);
      })
      .catch((error) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) setListError(safeMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setListLoading(false);
      });
    return () => controller.abort();
  }, [debouncedSearch, filters.adapter_kind, filters.camera_id, filters.enabled, filters.verification_status, page, refreshKey]);

  useEffect(() => {
    const controller = new AbortController();
    setRuntimeLoading(true);
    setRuntimeError(null);
    federationApi.runtimeCapabilities(controller.signal)
      .then(setRuntimeCapabilities)
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setRuntimeCapabilities(null);
        setRuntimeError(safeMessage(error));
        setRuntimeLoading(false);
      });
    return () => controller.abort();
  }, [runtimeRefreshKey]);

  useEffect(() => {
    if (!runtimeCapabilities) return;
    if (!runtimeCapabilities.available) {
      setRuntimeSessions([]);
      setRuntimeLoading(false);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const poll = async () => {
      controller?.abort();
      controller = new AbortController();
      try {
        const result = await federationApi.runtimeSessions(controller.signal);
        if (cancelled) return;
        setRuntimeSessions(result.items);
        setRuntimeError(null);
      } catch (error) {
        if (cancelled || (error instanceof DOMException && error.name === "AbortError")) return;
        setRuntimeError(safeMessage(error));
      } finally {
        if (!cancelled) {
          setRuntimeLoading(false);
          timer = setTimeout(() => void poll(), 5000);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [runtimeCapabilities]);

  const updateFilter = <K extends keyof FederationConnectionFilters>(key: K, value: FederationConnectionFilters[K]) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };

  const replaceConnection = useCallback((updated: FederationConnection) => {
    setConnections((current) => current.map((item) => item.id === updated.id ? updated : item));
    setRefreshKey((value) => value + 1);
  }, []);

  const probe = async (connection: FederationConnection) => {
    setBusyAction(`probe:${connection.id}`);
    setOperationError(null);
    try {
      replaceConnection(await federationApi.probe(connection.id));
    } catch (error) {
      setOperationError(safeMessage(error));
    } finally {
      setBusyAction(null);
    }
  };

  const toggleConnection = async () => {
    if (!confirmation) return;
    const { connection, action } = confirmation;
    setBusyAction(`${action}:${connection.id}`);
    setOperationError(null);
    try {
      const updated = action === "enable"
        ? await federationApi.enable(connection.id)
        : await federationApi.disable(connection.id);
      replaceConnection(updated);
      setConfirmation(null);
    } catch (error) {
      setOperationError(safeMessage(error));
    } finally {
      setBusyAction(null);
    }
  };

  const startRuntime = async (connection: FederationConnection) => {
    setRuntimeBusy(`start:${connection.id}`);
    setRuntimeError(null);
    try {
      const session = await federationApi.startRuntime(connection.id);
      upsertRuntimeSession(session);
      setSelectedConnectionId(null);
      setSelectedRuntimeSessionId(session.id);
    } catch (error) {
      setRuntimeError(safeMessage(error));
    } finally {
      setRuntimeBusy(null);
    }
  };

  const controlRuntime = async (session: RuntimeSession, action: "stop" | "restart") => {
    setRuntimeBusy(`${action}:${session.id}`);
    setRuntimeError(null);
    try {
      const updated = action === "stop"
        ? await federationApi.stopRuntime(session.id)
        : await federationApi.restartRuntime(session.id);
      upsertRuntimeSession(updated);
      if (action === "restart") {
        setSelectedConnectionId(null);
        setSelectedRuntimeSessionId(updated.id);
      }
    } catch (error) {
      setRuntimeError(safeMessage(error));
    } finally {
      setRuntimeBusy(null);
    }
  };

  const availableAdapters = adapters.filter(adapterIsAvailable);
  const selectedConnection = connections.find((connection) => connection.id === selectedConnectionId);
  const selectedAdapter = adapters.find((adapter) => adapter.kind === selectedConnection?.adapter_kind);
  const activeFilters = [filters.adapter_kind, filters.verification_status, filters.enabled].filter(Boolean).length;
  const statuses = useMemo(() => Object.keys(statistics?.by_status ?? {}).sort(), [statistics]);
  const sessionsByConnection = useMemo(() => {
    const result = new Map<string, RuntimeSession>();
    const stateWeight = (state: string) => ["live", "starting", "degraded", "backoff"].includes(state) ? 1 : 0;
    [...runtimeSessions]
      .sort((left, right) => stateWeight(right.state) - stateWeight(left.state) || new Date(right.state_changed_at).getTime() - new Date(left.state_changed_at).getTime())
      .forEach((session) => { if (!result.has(session.connection_id)) result.set(session.connection_id, session); });
    return result;
  }, [runtimeSessions]);
  const selectedConnectionRuntime = selectedConnectionId ? sessionsByConnection.get(selectedConnectionId) : undefined;
  const liveSessions = runtimeSessions.filter((session) => session.state === "live").length;
  const startingSessions = runtimeSessions.filter((session) => session.state === "starting").length;
  const runtimeAttention = runtimeSessions.filter((session) => ["degraded", "backoff", "failed", "unavailable"].includes(session.state)).length;
  const runtimeRestarts = runtimeSessions.reduce((sum, session) => sum + (session.restart_count ?? 0), 0);
  const selectedRuntimeSession = runtimeSessions.find((session) => session.id === selectedRuntimeSessionId);

  return (
    <div className="page federation-page">
      <header className="federation-hero">
        <div className="federation-hero__copy">
          <div className="page-header__context"><span>P0.3 Federation control plane</span><i />Vendor-neutral stream onboarding</div>
          <h1>Stream Federation</h1>
          <p>Normalize heterogeneous CCTV and VMS sources into encrypted connection profiles, prove bounded reachability, and supervise safe browser media delivery without exposing camera endpoints.</p>
          <div className="federation-hero__trust">
            <span><ShieldCheck size={15} />Encrypted source endpoints</span>
            <span><KeyRound size={15} />Encrypted device credentials</span>
            <span><Layers3 size={15} />Replaceable adapters</span>
          </div>
        </div>
        <div className="federation-hero__actions">
          <button type="button" className="button button--secondary" onClick={() => { refresh(); refreshRuntime(); }} disabled={catalogLoading || listLoading || runtimeLoading}><RefreshCw className={catalogLoading || listLoading || runtimeLoading ? "spin" : undefined} size={16} />Refresh control plane</button>
          <button type="button" className="button button--secondary government-feed-button" onClick={() => setGovernmentFeedOpen(true)}><CloudDownload size={17} />Government grid</button>
          <button type="button" className="button button--secondary" onClick={() => setCredentialVaultOpen(true)}><KeyRound size={17} />Credential vault</button>
          <button type="button" className="button button--primary" onClick={() => setOnboardingOpen(true)} disabled={catalogLoading || !availableAdapters.length}><Plus size={17} />Onboard connection</button>
        </div>
      </header>

      {catalogError ? <div className="federation-service-error" role="alert"><Unplug size={20} /><span><strong>Federation service is not available</strong><small>{catalogError}</small></span><button type="button" onClick={refresh}>Retry</button></div> : null}
      {operationError ? <div className="federation-operation-error" role="alert"><OctagonAlert size={18} /><span><strong>Operation did not complete</strong><small>{operationError}</small></span><button type="button" aria-label="Dismiss operation error" onClick={() => setOperationError(null)}><X size={16} /></button></div> : null}
      {runtimeError ? <div className="federation-operation-error runtime-operation-error" role="alert"><OctagonAlert size={18} /><span><strong>Media runtime operation did not complete</strong><small>{runtimeError}</small></span><button type="button" aria-label="Retry media runtime" onClick={refreshRuntime}><RefreshCw size={16} /></button></div> : null}

      <section className="federation-kpis" aria-label="Federation key performance indicators">
        <FederationKpi icon={Cable} label="Connection profiles" value={statistics?.total} note="Encrypted source definitions" loading={catalogLoading} />
        <FederationKpi icon={CheckCircle2} label="Reachable probes" value={statistics?.reachable} note="Bounded handshake succeeded" tone="healthy" loading={catalogLoading} />
        <FederationKpi icon={OctagonAlert} label="Needs attention" value={statistics?.attention} note="Failed or unreachable" tone="danger" loading={catalogLoading} />
        <FederationKpi icon={CircleDashed} label="Unverified" value={statistics?.unverified} note="Probe evidence pending" tone="warning" loading={catalogLoading} />
        <FederationKpi icon={Zap} label="Candidate profiles" value={statistics?.enabled} note="Enabled; sustained stream unverified" tone="cyan" loading={catalogLoading} />
        <FederationKpi icon={Boxes} label="Available adapters" value={catalogLoading ? undefined : availableAdapters.length} note={`${adapters.length} registered manifests`} tone="violet" loading={catalogLoading} />
      </section>

      <section className="federation-topology" aria-label="Live federation topology">
        <header><div><span className="panel-kicker">Measured integration posture</span><h2>Federation readiness path</h2></div><span className="topology-freshness"><Activity size={14} />{statistics?.last_probe_at ? `Probed ${relativeTime(statistics.last_probe_at)}` : "No probe evidence yet"}</span></header>
        <div className="topology-flow">
          <TopologyNode icon={DatabaseZap} step="01" title="Heterogeneous sources" value={statistics?.total} unit="profiles" detail={topAdapterSummary(statistics)} loading={catalogLoading} />
          <TopologyLink active={Boolean(statistics?.total)} label="encrypted input" />
          <TopologyNode icon={Boxes} step="02" title="Secure adapters" value={availableAdapters.length} unit="available" detail={`${adapters.length} runtime manifests registered`} loading={catalogLoading} />
          <TopologyLink active={Boolean(availableAdapters.length && statistics?.total)} label="normalized metadata" />
          <TopologyNode icon={Radar} step="03" title="Bounded probe" value={statistics?.reachable} unit="reachable" detail={`${statistics?.attention ?? 0} requiring intervention`} loading={catalogLoading} />
          <TopologyLink active={Boolean(runtimeCapabilities?.available)} label="supervised media" />
          <TopologyNode icon={Cpu} step="04" title="Browser media runtime" value={runtimeCapabilities?.available ? liveSessions : undefined} unit="live" detail={runtimeCapabilities?.available ? `${startingSessions} starting · AI inference remains downstream` : "Runtime unavailable; sustained decode, FPS and frame quality are not yet verified. AI inference remains downstream."} loading={runtimeLoading} />
        </div>
      </section>

      <section className="runtime-overview" aria-label="Browser media runtime posture">
        <header className="runtime-overview__header">
          <div><span className="runtime-overview__icon"><Play size={18} /></span><span><small className="panel-kicker">P0.3R / Supervised delivery</small><h2>Browser media runtime</h2><p>Same-origin HLS delivery with watchdog supervision. This proves browser playback, not AI analytics.</p></span></div>
          {runtimeLoading ? <span className="runtime-availability runtime-availability--loading"><LoaderCircle className="spin" size={14} />Checking runtime</span> : <span className={`runtime-availability${runtimeCapabilities?.available ? " runtime-availability--available" : ""}`}>{runtimeCapabilities?.available ? <CheckCircle2 size={14} /> : <CircleOff size={14} />}{runtimeCapabilities?.available ? "Runtime available" : "Runtime unavailable"}</span>}
        </header>
        {runtimeLoading && !runtimeCapabilities ? <RuntimeOverviewSkeleton /> : runtimeCapabilities?.available ? (
          <>
            <div className="runtime-overview__metrics">
              <RuntimeOverviewMetric label="Live sessions" value={liveSessions} tone="live" detail="Delivering playlist media" />
              <RuntimeOverviewMetric label="Starting" value={startingSessions} detail="Awaiting progress evidence" />
              <RuntimeOverviewMetric label="Needs attention" value={runtimeAttention} tone={runtimeAttention ? "attention" : "neutral"} detail="Degraded, backoff, or failed" />
              <RuntimeOverviewMetric label="Supervisor restarts" value={runtimeRestarts} detail="Observed across sessions" />
            </div>
            <div className="runtime-supervision-strip">
              <span><small>Output</small><strong>{titleCase(runtimeCapabilities.output_protocol)}</strong></span>
              <span><small>Segments</small><strong>{runtimeCapabilities.segment_duration_seconds}s × {runtimeCapabilities.playlist_window}</strong></span>
              <span><small>Watchdog</small><strong>{runtimeCapabilities.supervision.watchdog_seconds}s</strong></span>
              <span><small>Maximum backoff</small><strong>{runtimeCapabilities.supervision.max_backoff_seconds}s</strong></span>
              <span><small>Credential resolver</small><strong>{titleCase(runtimeCapabilities.credential_resolver_mode)}</strong></span>
              <span className="runtime-supervision-strip__boundary"><ShieldCheck size={15} /><small>Module boundary</small><strong>{runtimeCapabilities.boundary || "Browser delivery only; AI remains downstream"}</strong></span>
            </div>
          </>
        ) : (
          <div className="runtime-unavailable-state"><span><CircleOff size={24} /></span><div><strong>Media runtime is not available in this deployment</strong><p>Connection onboarding, probes, and encrypted profile management remain operational. Live controls stay disabled until the server advertises runtime availability.</p></div><button className="button button--quiet" type="button" onClick={refreshRuntime}><RefreshCw size={15} />Retry runtime</button></div>
        )}
      </section>

      <section className="federation-workspace">
        <header className="federation-workspace__header">
          <div><span className="workspace-header__icon"><Network size={17} /></span><span><small className="panel-kicker">Operational inventory</small><h2>Connection profiles</h2></span></div>
          <span className="inventory-total">{total.toLocaleString("en-IN")} profile{total === 1 ? "" : "s"}</span>
        </header>
        <div className="federation-filters">
          <label className="federation-search"><Search size={17} /><input aria-label="Search connection profiles" type="search" value={filters.search} onChange={(event) => updateFilter("search", event.target.value)} placeholder="Search profile, camera, code, district, or fingerprint" />{filters.search ? <button type="button" aria-label="Clear connection search" onClick={() => updateFilter("search", "")}><X size={15} /></button> : null}</label>
          <div className="federation-filter-controls">
            <span><Filter size={15} />Filters{activeFilters ? <b>{activeFilters}</b> : null}</span>
            <label><span className="sr-only">Adapter filter</span><select aria-label="Adapter filter" value={filters.adapter_kind} onChange={(event) => updateFilter("adapter_kind", event.target.value)}><option value="">All adapters</option>{adapters.map((adapter) => <option key={adapter.kind} value={adapter.kind}>{adapter.label}</option>)}</select></label>
            <label><span className="sr-only">Verification filter</span><select aria-label="Verification filter" value={filters.verification_status} onChange={(event) => updateFilter("verification_status", event.target.value)}><option value="">All verification states</option>{statuses.map((status) => <option key={status} value={status}>{titleCase(status)}</option>)}</select></label>
            <label><span className="sr-only">Activation filter</span><select aria-label="Activation filter" value={filters.enabled} onChange={(event) => updateFilter("enabled", event.target.value as FederationConnectionFilters["enabled"])}><option value="">Enabled + disabled</option><option value="true">Enabled only</option><option value="false">Disabled only</option></select></label>
            {activeFilters ? <button className="clear-federation-filters" type="button" onClick={() => { setFilters((current) => ({ ...emptyFilters, search: current.search })); setPage(1); }}><SlidersHorizontal size={14} />Clear filters</button> : null}
          </div>
        </div>

        {listError ? <div className="federation-list-state federation-list-state--error" role="alert"><OctagonAlert size={23} /><span><strong>Connection inventory unavailable</strong><small>{listError}</small></span><button type="button" className="button button--quiet" onClick={refresh}>Retry</button></div> : null}
        {!listError ? (
          <div className={`federation-table-wrap${listLoading ? " federation-table-wrap--loading" : ""}`}>
            <table className="federation-table">
              <thead><tr><th>Connection profile</th><th>Registry camera</th><th>Adapter profile</th><th>Verification</th><th>Probe evidence</th><th>Media runtime</th><th>Activation</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {connections.map((connection) => {
                  const adapter = adapters.find((item) => item.kind === connection.adapter_kind);
                  const runtimeSession = sessionsByConnection.get(connection.id);
                  const probing = busyAction === `probe:${connection.id}`;
                  const toggling = busyAction === `enable:${connection.id}` || busyAction === `disable:${connection.id}`;
                  return (
                    <tr key={connection.id} className={federationStatusTone(connection.verification_status) === "attention" ? "federation-row--attention" : undefined}>
                      <td><button className="connection-identity" type="button" onClick={() => setSelectedConnectionId(connection.id)}><span className="connection-identity__glyph"><Cable size={17} /></span><span><strong>{connection.name}</strong><small>{titleCase(connection.stream_role)} · Priority {connection.priority}</small></span></button></td>
                      <td><div className="federation-camera-cell"><strong>{connection.camera_name}</strong><code>{connection.camera_code}</code><small>{connection.department_name || "Department unavailable"} · {connectionLocation(connection)}</small></div></td>
                      <td><div className="adapter-cell"><span><Boxes size={14} />{connection.adapter_label || adapter?.label || titleCase(connection.adapter_kind)}</span><code>{safeEndpointDisplay(connection.endpoint_display)}</code></div></td>
                      <td><FederationStatusBadge value={connection.verification_status} />{connection.failure_count ? <small className="failure-count">{connection.failure_count} consecutive failure{connection.failure_count === 1 ? "" : "s"}</small> : null}</td>
                      <td><div className="probe-evidence"><strong>{connection.last_probe_latency_ms == null ? "—" : `${Math.round(connection.last_probe_latency_ms)} ms`}</strong><small>{formatTimestamp(connection.last_probe_at)}</small></div></td>
                      <td><ConnectionRuntimeControl
                        connection={connection}
                        session={runtimeSession}
                        capabilities={runtimeCapabilities}
                        busy={runtimeBusy}
                        onStart={startRuntime}
                        onOpen={(session) => { setSelectedConnectionId(null); setSelectedRuntimeSessionId(session.id); }}
                        onStop={(session) => void controlRuntime(session, "stop")}
                        onRestart={(session) => void controlRuntime(session, "restart")}
                      /></td>
                      <td><button type="button" className={`activation-control${connection.enabled ? " activation-control--enabled" : ""}`} aria-label={`${connection.enabled ? "Disable" : "Enable"} ${connection.name}`} onClick={() => setConfirmation({ connection, action: connection.enabled ? "disable" : "enable" })} disabled={toggling}>{toggling ? <LoaderCircle className="spin" size={14} /> : connection.enabled ? <CheckCircle2 size={14} /> : <CircleOff size={14} />}{connection.enabled ? "Enabled" : "Disabled"}</button></td>
                      <td><div className="federation-row-actions"><button type="button" aria-label={`Probe ${connection.name}`} title={adapter?.probe_supported === false ? "Adapter does not support probing" : "Run secure probe"} onClick={() => probe(connection)} disabled={probing || adapter?.probe_supported === false}>{probing ? <LoaderCircle className="spin" size={16} /> : <Radar size={16} />}</button><button type="button" aria-label={`Open ${connection.name} details`} title="Open secure profile" onClick={() => setSelectedConnectionId(connection.id)}><ChevronRight size={17} /></button></div></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {listLoading && !connections.length ? <TableSkeleton /> : null}
            {!listLoading && !connections.length ? <div className="federation-list-state"><span className="federation-empty-orbit"><Network size={27} /></span><strong>{activeFilters || filters.search ? "No connection profiles match" : "No stream connections onboarded"}</strong><p>{activeFilters || filters.search ? "Change or clear the filters to widen the search." : "Create the first encrypted adapter profile for a registered camera."}</p>{!activeFilters && !filters.search && availableAdapters.length ? <button type="button" className="button button--primary" onClick={() => setOnboardingOpen(true)}><Plus size={16} />Onboard first connection</button> : null}</div> : null}
          </div>
        ) : null}
        {pages > 1 ? <footer className="federation-pagination"><span>Page {page} of {pages} · {total.toLocaleString("en-IN")} records</span><div><button type="button" aria-label="Previous connection page" disabled={page <= 1 || listLoading} onClick={() => setPage((current) => current - 1)}><ChevronLeft size={16} />Previous</button><button type="button" aria-label="Next connection page" disabled={page >= pages || listLoading} onClick={() => setPage((current) => current + 1)}>Next<ChevronRight size={16} /></button></div></footer> : null}
      </section>

      <section className="adapter-catalog">
        <header><div><span className="panel-kicker">Runtime manifests</span><h2>Adapter catalogue</h2><p>Only capabilities declared by the federation API are shown.</p></div><span>{availableAdapters.length} of {adapters.length} available</span></header>
        {catalogLoading ? <div className="adapter-card-grid">{[0, 1, 2].map((item) => <div className="adapter-card adapter-card--skeleton" key={item}><i className="skeleton" /><i className="skeleton" /><i className="skeleton" /></div>)}</div> : adapters.length ? (
          <div className="adapter-card-grid">
            {adapters.map((adapter) => <AdapterCard key={adapter.kind} adapter={adapter} />)}
          </div>
        ) : <div className="adapter-empty"><Boxes size={24} /><span><strong>No adapter manifests registered</strong><small>Deploy at least one supported adapter before creating connection profiles.</small></span></div>}
      </section>

      <FederationOnboardingModal open={onboardingOpen} adapters={adapters} credentialRefreshKey={credentialRefreshKey} onClose={() => setOnboardingOpen(false)} onCreated={replaceConnection} />
      <GovernmentFeedSyncModal open={governmentFeedOpen} onClose={() => setGovernmentFeedOpen(false)} onSynced={() => { refresh(); refreshRuntime(); }} />
      <CredentialVaultModal open={credentialVaultOpen} onClose={() => setCredentialVaultOpen(false)} onChanged={() => setCredentialRefreshKey((value) => value + 1)} />
      <FederationConnectionDrawer connectionId={selectedConnectionId} initialConnection={selectedConnection} runtimeSession={selectedConnectionRuntime} adapter={selectedAdapter} onClose={() => setSelectedConnectionId(null)} onChanged={replaceConnection} />
      <LiveRuntimeDrawer sessionId={selectedRuntimeSessionId} initialSession={selectedRuntimeSession} capabilities={runtimeCapabilities} onClose={() => setSelectedRuntimeSessionId(null)} onSessionChanged={upsertRuntimeSession} />
      <Modal open={Boolean(confirmation)} onClose={() => setConfirmation(null)} busy={Boolean(busyAction)} title={`${confirmation?.action === "disable" ? "Disable" : "Enable"} connection profile`} eyebrow="Controlled state change">
        {confirmation ? <div className="confirmation-body"><span className={`confirmation-body__icon confirmation-body__icon--${confirmation.action}`} >{confirmation.action === "disable" ? <CircleOff size={24} /> : <CheckCircle2 size={24} />}</span><div><h3>{confirmation.connection.name}</h3><p>{confirmation.action === "disable" ? "The profile will stop participating in adapter operations. Its encrypted configuration and audit history will be retained." : "The profile will participate in bounded adapter operations. Browser delivery is supervised separately, while AI inference remains a downstream module."}</p><dl><div><dt>Camera</dt><dd>{confirmation.connection.camera_code}</dd></div><div><dt>Current status</dt><dd>{titleCase(confirmation.connection.verification_status)}</dd></div></dl></div></div> : null}
        <footer className="modal__footer"><button type="button" className="button button--secondary" onClick={() => setConfirmation(null)} disabled={Boolean(busyAction)}>Cancel</button><button type="button" className={`button ${confirmation?.action === "disable" ? "button--danger" : "button--primary"}`} onClick={toggleConnection} disabled={Boolean(busyAction)}>{busyAction ? <LoaderCircle className="spin" size={16} /> : confirmation?.action === "disable" ? <CircleOff size={16} /> : <CheckCircle2 size={16} />}{confirmation?.action === "disable" ? "Disable profile" : "Enable profile"}</button></footer>
      </Modal>
    </div>
  );
}

function ConnectionRuntimeControl({
  connection,
  session,
  capabilities,
  busy,
  onStart,
  onOpen,
  onStop,
  onRestart,
}: {
  connection: FederationConnection;
  session?: RuntimeSession;
  capabilities: RuntimeCapabilities | null;
  busy: string | null;
  onStart: (connection: FederationConnection) => Promise<void>;
  onOpen: (session: RuntimeSession) => void;
  onStop: (session: RuntimeSession) => void;
  onRestart: (session: RuntimeSession) => void;
}) {
  const runtimeAvailable = Boolean(capabilities?.available);
  const adapterSupported = Boolean(capabilities?.supported_adapter_kinds?.includes(connection.adapter_kind));
  const starting = busy === `start:${connection.id}`;
  const stopping = session ? busy === `stop:${session.id}` : false;
  const restarting = session ? busy === `restart:${session.id}` : false;
  const active = session ? ["starting", "live", "degraded", "backoff"].includes(session.state) : false;

  if (!runtimeAvailable || !adapterSupported) {
    return <div className="connection-runtime connection-runtime--unavailable"><RuntimeStatusBadge state="unavailable" /><small>{runtimeAvailable ? "Adapter not supported" : "Service pending"}</small></div>;
  }

  if (!session) {
    return <div className="connection-runtime"><span className="runtime-not-started">Not started</span><button type="button" className="runtime-action runtime-action--start" aria-label={`Start live view for ${connection.name}`} onClick={() => void onStart(connection)} disabled={starting || !connection.enabled} title={connection.enabled ? "Start supervised browser delivery" : "Enable this profile before starting media delivery"}>{starting ? <LoaderCircle className="spin" size={14} /> : <Play size={14} />}{starting ? "Starting…" : "Start live view"}</button></div>;
  }

  return <div className="connection-runtime"><RuntimeStatusBadge state={session.state} /><div className="connection-runtime__actions"><button type="button" className="runtime-action runtime-action--open" onClick={() => onOpen(session)} aria-label={`Open live runtime for ${connection.name}`}><Play size={13} />{session.state === "live" || session.state === "degraded" ? "View live" : "View status"}</button>{active ? <button type="button" className="runtime-icon-action" onClick={() => onStop(session)} disabled={stopping || restarting} aria-label={`Stop live runtime for ${connection.name}`} title="Stop runtime">{stopping ? <LoaderCircle className="spin" size={14} /> : <Square size={13} />}</button> : null}<button type="button" className="runtime-icon-action" onClick={() => onRestart(session)} disabled={stopping || restarting} aria-label={`Restart live runtime for ${connection.name}`} title="Restart runtime">{restarting ? <LoaderCircle className="spin" size={14} /> : <RotateCcw size={13} />}</button></div></div>;
}

function RuntimeOverviewMetric({ label, value, detail, tone = "neutral" }: { label: string; value: number; detail: string; tone?: "neutral" | "live" | "attention" }) {
  return <article className={`runtime-overview-metric runtime-overview-metric--${tone}`}><small>{label}</small><strong>{value.toLocaleString("en-IN")}</strong><span>{detail}</span></article>;
}

function RuntimeOverviewSkeleton() {
  return <div className="runtime-overview-skeleton" aria-label="Loading media runtime posture">{[0, 1, 2, 3].map((item) => <span key={item}><i className="skeleton skeleton--number" /><i className="skeleton" /></span>)}</div>;
}

function FederationKpi({ icon: Icon, label, value, note, loading, tone = "neutral" }: { icon: typeof Network; label: string; value?: number; note: string; loading: boolean; tone?: "neutral" | "healthy" | "danger" | "warning" | "cyan" | "violet" }) {
  return <article className={`federation-kpi federation-kpi--${tone}`}><span className="federation-kpi__icon"><Icon size={20} /></span><span><small>{label}</small>{loading && value === undefined ? <i className="skeleton skeleton--number" /> : <strong>{value == null ? "—" : value.toLocaleString("en-IN")}</strong>}<em>{note}</em></span></article>;
}

function TopologyNode({ icon: Icon, step, title, value, unit, detail, loading }: { icon: typeof Network; step: string; title: string; value?: number; unit: string; detail: string; loading: boolean }) {
  return <article className="topology-node"><header><span>{step}</span><Icon size={20} /></header><h3>{title}</h3><div>{loading && value === undefined ? <i className="skeleton skeleton--number" /> : <strong>{value == null ? "—" : value.toLocaleString("en-IN")}</strong>}<small>{unit}</small></div><p>{detail}</p></article>;
}

function TopologyLink({ active, label }: { active: boolean; label: string }) {
  return <div className={`topology-link${active ? " topology-link--active" : ""}`}><span><i /><i /><i /></span><small>{label}</small><ArrowRight size={18} /></div>;
}

function AdapterCard({ adapter }: { adapter: FederationAdapter }) {
  const available = adapterIsAvailable(adapter);
  const profileCapabilities = [
    { label: "Probe", active: adapter.probe_supported, icon: Radar },
    { label: "Discovery", active: adapter.discovery_supported, icon: Search },
    { label: "Handoff contract", active: adapter.stream_handoff_supported, icon: Zap },
  ];
  return <article className={`adapter-card${available ? "" : " adapter-card--unavailable"}`}><header><span className="adapter-card__icon"><Boxes size={20} /></span><span><strong>{adapter.label}</strong><code>{adapter.kind} · v{adapter.version}</code></span><em className={available ? "adapter-availability adapter-availability--up" : "adapter-availability"}>{available ? <CheckCircle2 size={13} /> : <CircleOff size={13} />}{available ? "Available" : "Unavailable"}</em></header><p>{adapter.description}</p><div className="adapter-schemes">{adapter.schemes.map((scheme) => <code key={scheme}>{scheme.replace("://", "")}</code>)}</div><div className="adapter-capabilities">{profileCapabilities.map(({ label, active, icon: Icon }) => <span className={active ? "adapter-capability adapter-capability--active" : "adapter-capability"} key={label}><Icon size={13} />{label}<i>{active ? "Yes" : "No"}</i></span>)}</div>{adapter.capabilities.length ? <footer>{adapter.capabilities.slice(0, 5).map((capability) => <span key={capability}>{titleCase(capability)}</span>)}</footer> : null}{!available && adapter.availability_message ? <div className="adapter-unavailable-reason"><OctagonAlert size={14} />{adapter.availability_message}</div> : null}</article>;
}

function topAdapterSummary(statistics?: FederationStatistics | null): string {
  const adapters = Object.entries(statistics?.by_adapter ?? {}).sort((a, b) => b[1] - a[1]);
  if (!adapters.length) return "No source profiles registered";
  return adapters.slice(0, 2).map(([name, count]) => `${titleCase(name)} ${count}`).join(" · ");
}

function TableSkeleton() {
  return <div className="federation-table-skeleton" aria-label="Loading connection profiles">{[0, 1, 2, 3].map((row) => <span key={row}><i className="skeleton" /><i className="skeleton" /><i className="skeleton" /><i className="skeleton" /></span>)}</div>;
}
