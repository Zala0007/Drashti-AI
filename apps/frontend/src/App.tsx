import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell, type AppPage } from "./components/AppShell";
import { CameraDetailDrawer } from "./components/CameraDetailDrawer";
import { ApiError, federationApi, registryApi } from "./lib/api";
import { emptyCameraFilters } from "./lib/registryView";
import { CommandCentrePage } from "./pages/CommandCentrePage";
import type { FederationStatistics } from "./types/federation";
import type { Camera, CameraGeoJson, CameraStatistics, Department } from "./types/registry";

const CameraRegistryPage = lazy(() => import("./pages/CameraRegistryPage").then((module) => ({ default: module.CameraRegistryPage })));
const AIIntelligencePage = lazy(() => import("./pages/AIIntelligencePage").then((module) => ({ default: module.AIIntelligencePage })));
const VisualIntelligencePage = lazy(() => import("./pages/VisualIntelligencePage").then((module) => ({ default: module.VisualIntelligencePage })));
const CameraHealthPage = lazy(() => import("./pages/CameraHealthPage").then((module) => ({ default: module.CameraHealthPage })));
const CasesEvidencePage = lazy(() => import("./pages/CasesEvidencePage").then((module) => ({ default: module.CasesEvidencePage })));
const CoverageIntelligencePage = lazy(() => import("./pages/CoverageIntelligencePage").then((module) => ({ default: module.CoverageIntelligencePage })));
const GisOperationsPage = lazy(() => import("./pages/GisOperationsPage").then((module) => ({ default: module.GisOperationsPage })));
const LiveOperationsPage = lazy(() => import("./pages/LiveOperationsPage").then((module) => ({ default: module.LiveOperationsPage })));
const SpecialInvestigationPage = lazy(() => import("./pages/SpecialInvestigationPage").then((module) => ({ default: module.SpecialInvestigationPage })));
const WatchlistAlertsPage = lazy(() => import("./pages/WatchlistAlertsPage").then((module) => ({ default: module.WatchlistAlertsPage })));
const federationPageModule = import("./pages/StreamFederationPage");
const StreamFederationPage = lazy(() => federationPageModule.then((module) => ({ default: module.StreamFederationPage })));

const routes: Record<string, AppPage> = {
  "#/command": "command",
  "#/ai": "ai",
  "#/visual": "visual",
  "#/investigation": "investigation",
  "#/alerts": "alerts",
  "#/cases": "cases",
  "#/health": "health",
  "#/coverage": "coverage",
  "#/federation": "federation",
  "#/gis": "gis",
  "#/live": "live",
  "#/registry": "registry",
};

const messageFor = (error: unknown): string =>
  error instanceof ApiError ? error.message : "The registry service could not provide the operational view.";

const initialPage = (): AppPage => routes[window.location.hash] ?? "command";

export default function App() {
  const [activePage, setActivePage] = useState<AppPage>(initialPage);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [statistics, setStatistics] = useState<CameraStatistics | null>(null);
  const [geoJson, setGeoJson] = useState<CameraGeoJson | null>(null);
  const [attentionCameras, setAttentionCameras] = useState<Camera[]>([]);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [apiConnected, setApiConnected] = useState<boolean | null>(null);
  const [federationStatistics, setFederationStatistics] = useState<FederationStatistics | null>(null);
  const [federationConnected, setFederationConnected] = useState<boolean | null>(null);
  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);
  const [gisFocusedCameraId, setGisFocusedCameraId] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);
  const handleDepartmentCreated = useCallback((department: Department) => {
    setDepartments((current) => [...current.filter((item) => item.id !== department.id), department]
      .sort((left, right) => left.name.localeCompare(right.name)));
  }, []);
  const handleFederationStatistics = useCallback((value: FederationStatistics) => {
    setFederationStatistics(value);
    setFederationConnected(true);
  }, []);

  useEffect(() => {
    const onHashChange = () => setActivePage(initialPage());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = useCallback((page: AppPage) => {
    window.history.pushState(null, "", `#/${page}`);
    setSelectedCameraId(null);
    if (page !== "gis") setGisFocusedCameraId(null);
    setActivePage(page);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setOverviewLoading(true);
    setOverviewError(null);
    const offlineFilters = { ...emptyCameraFilters, health: "offline" as const };
    const degradedFilters = { ...emptyCameraFilters, health: "degraded" as const };

    Promise.allSettled([
      registryApi.statistics(emptyCameraFilters, controller.signal),
      registryApi.geoJson(emptyCameraFilters, controller.signal),
      registryApi.departments(controller.signal),
      registryApi.cameras(offlineFilters, 1, 8, controller.signal),
      registryApi.cameras(degradedFilters, 1, 8, controller.signal),
    ]).then((results) => {
      if (controller.signal.aborted) return;
      const [statsResult, mapResult, departmentResult, offlineResult, degradedResult] = results;
      if (statsResult.status === "fulfilled") setStatistics(statsResult.value);
      if (mapResult.status === "fulfilled") setGeoJson(mapResult.value);
      if (departmentResult.status === "fulfilled") setDepartments(departmentResult.value);

      const attention = [offlineResult, degradedResult]
        .flatMap((result) => result.status === "fulfilled" ? result.value.items : []);
      setAttentionCameras(attention);

      const registryAvailable = statsResult.status === "fulfilled" || mapResult.status === "fulfilled";
      setApiConnected(registryAvailable);
      if (registryAvailable) setLastSyncedAt(new Date());
      if (statsResult.status === "rejected" || mapResult.status === "rejected") {
        const failure = statsResult.status === "rejected" ? statsResult.reason : mapResult.status === "rejected" ? mapResult.reason : null;
        setOverviewError(messageFor(failure));
      }
      setOverviewLoading(false);
    });

    return () => controller.abort();
  }, [refreshKey]);

  useEffect(() => {
    const controller = new AbortController();
    setFederationConnected(null);
    federationApi.statistics(controller.signal)
      .then((value) => {
        setFederationStatistics(value);
        setFederationConnected(true);
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setFederationStatistics(null);
        setFederationConnected(false);
      });
    return () => controller.abort();
  }, [refreshKey]);

  const lastSynchronized = useMemo(() => lastSyncedAt ? new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(lastSyncedAt) : "Not synchronized", [lastSyncedAt]);

  return (
    <AppShell
      apiConnected={apiConnected}
      activePage={activePage}
      onNavigate={navigate}
      statistics={statistics}
      federationStatistics={federationStatistics}
      federationConnected={federationConnected}
    >
      <Suspense fallback={<div className="advanced-loading"><span className="spin">◌</span>Opening operational workspace…</div>}>
      {activePage === "command" ? (
        <CommandCentrePage
          statistics={statistics}
          geoJson={geoJson}
          departments={departments}
          attentionCameras={attentionCameras}
          loading={overviewLoading}
          error={overviewError}
          lastSynchronized={lastSynchronized}
          selectedCameraId={selectedCameraId}
          onSelectCamera={setSelectedCameraId}
          onRetry={refresh}
          onOpenGis={() => navigate("gis")}
          federationStatistics={federationStatistics}
          federationConnected={federationConnected}
          onOpenFederation={() => navigate("federation")}
        />
      ) : null}

      {activePage === "ai" ? <AIIntelligencePage /> : null}

      {activePage === "visual" ? <VisualIntelligencePage /> : null}

      {activePage === "federation" ? (
        <StreamFederationPage
          overviewStatistics={federationStatistics}
          onStatisticsChanged={handleFederationStatistics}
        />
      ) : null}

      {activePage === "investigation" ? <SpecialInvestigationPage /> : null}

      {activePage === "alerts" ? <WatchlistAlertsPage /> : null}

      {activePage === "cases" ? <CasesEvidencePage /> : null}

      {activePage === "health" ? <CameraHealthPage /> : null}

      {activePage === "coverage" ? <CoverageIntelligencePage /> : null}

      {activePage === "gis" ? (
        <GisOperationsPage
          departments={departments}
          focusedCameraId={gisFocusedCameraId}
          onFocusCamera={setGisFocusedCameraId}
          onOpenCamera={setSelectedCameraId}
        />
      ) : null}

      {activePage === "live" ? <LiveOperationsPage /> : null}

      {activePage === "registry" ? (
        <CameraRegistryPage
          departments={departments}
          selectedCameraId={selectedCameraId}
          onSelectCamera={setSelectedCameraId}
          onRegistryChanged={refresh}
          onDepartmentCreated={handleDepartmentCreated}
        />
      ) : null}
      </Suspense>

      {activePage !== "registry" ? <CameraDetailDrawer cameraId={selectedCameraId} onClose={() => setSelectedCameraId(null)} /> : null}
    </AppShell>
  );
}
