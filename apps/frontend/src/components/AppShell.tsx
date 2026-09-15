import {
  BellRing,
  BriefcaseBusiness,
  BrainCircuit,
  Camera,
  ChevronLeft,
  ChevronRight,
  Cctv,
  HeartPulse,
  Map,
  MapPinned,
  Menu,
  Moon,
  Network,
  ScanSearch,
  ScanEye,
  ShieldCheck,
  Sun,
  Video,
  X,
} from "lucide-react";
import { useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import type { FederationStatistics } from "../types/federation";
import type { CameraStatistics } from "../types/registry";

export type AppPage = "command" | "ai" | "advanced" | "visual" | "investigation" | "alerts" | "cases" | "health" | "coverage" | "federation" | "live" | "gis" | "registry";

interface AppShellProps {
  children: ReactNode;
  apiConnected: boolean | null;
  activePage: AppPage;
  onNavigate: (page: AppPage) => void;
  statistics: CameraStatistics | null;
  federationStatistics: FederationStatistics | null;
  federationConnected: boolean | null;
}

const pageMeta: Record<AppPage, { label: string; eyebrow: string }> = {
  advanced: { label: "Advanced Features", eyebrow: "Draw, monitor and track on a selected feed" },
  command: { label: "Command Centre", eyebrow: "State Operations Centre" },
  ai: { label: "Video Analytics", eyebrow: "Evidence review and model output" },
  visual: { label: "Visual Intelligence", eyebrow: "Search by appearance when the plate is unknown" },
  investigation: { label: "Special Investigation", eyebrow: "Restricted vehicle pursuit intelligence" },
  alerts: { label: "Watchlist Alerts", eyebrow: "Controlled alert review" },
  cases: { label: "Cases & Evidence", eyebrow: "Controlled investigation records" },
  health: { label: "Camera Health", eyebrow: "Operational resilience intelligence" },
  coverage: { label: "Coverage Intelligence", eyebrow: "Statewide surveillance planning" },
  federation: { label: "Stream Federation", eyebrow: "Secure integration control plane" },
  live: { label: "Live Operations", eyebrow: "Live feeds and edge processing" },
  gis: { label: "GIS Operations", eyebrow: "Statewide geospatial operations" },
  registry: { label: "Camera Registry", eyebrow: "Federated asset control" },
};

const navSections = [
  {
    label: "Operations",
    items: [
      { id: "command", label: "Command Centre", icon: Cctv },
      { id: "live", label: "Live Operations", icon: Video },
      { id: "gis", label: "GIS Operations", icon: Map },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { id: "ai", label: "Video Analytics", icon: BrainCircuit },
      { id: "advanced", label: "Advanced Features", icon: ScanEye },
      { id: "visual", label: "Visual Intelligence", icon: ScanEye },
      { id: "investigation", label: "Special Investigation", icon: ScanSearch },
      { id: "alerts", label: "Watchlist Alerts", icon: BellRing },
      { id: "cases", label: "Cases & Evidence", icon: BriefcaseBusiness },
    ],
  },
  {
    label: "Administration",
    items: [
      { id: "health", label: "Camera Health", icon: HeartPulse },
      { id: "coverage", label: "Coverage Intelligence", icon: MapPinned },
      { id: "federation", label: "Stream Federation", icon: Network },
      { id: "registry", label: "Camera Registry", icon: Camera },
    ],
  },
] as const;

type Theme = "dark" | "light";

function initialTheme(): Theme {
  try {
    const saved = window.localStorage.getItem("drishti-theme");
    if (saved === "dark" || saved === "light") return saved;
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function AppShell({
  children,
  apiConnected,
  activePage,
  onNavigate,
  statistics,
  federationStatistics,
  federationConnected,
}: AppShellProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useLayoutEffect(() => {
    document.documentElement.classList.add("theme-changing");
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      theme === "dark" ? "#101919" : "#f5f6f3",
    );
    try {
      window.localStorage.setItem("drishti-theme", theme);
    } catch {
      // The selected theme still applies for this session when storage is blocked.
    }
    const timer = window.setTimeout(() => {
      document.documentElement.classList.remove("theme-changing");
    }, 0);
    return () => window.clearTimeout(timer);
  }, [theme]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileNavOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [mobileNavOpen]);

  useEffect(() => {
    document.title = `${pageMeta[activePage].label} · Drashti AI`;
    setMobileNavOpen(false);
  }, [activePage]);

  const navigate = (page: AppPage) => {
    onNavigate(page);
    setMobileNavOpen(false);
  };

  return (
    <div className={`app-shell${collapsed ? " app-shell--collapsed" : ""}`}>
      <a className="skip-link" href="#main-content" onClick={(event) => { event.preventDefault(); document.getElementById("main-content")?.focus(); }}>Skip to workspace</a>
      <header className="mobile-header">
        <button type="button" onClick={() => setMobileNavOpen((open) => !open)} aria-label="Toggle navigation" aria-expanded={mobileNavOpen} aria-controls="primary-navigation">
          {mobileNavOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
        <Brand compact />
        <ThemeToggle theme={theme} compact onToggle={() => setTheme((value) => value === "dark" ? "light" : "dark")} />
      </header>

      <aside className={`sidebar${mobileNavOpen ? " sidebar--open" : ""}${collapsed ? " sidebar--collapsed" : ""}`}>
        <Brand collapsed={collapsed} />
        <button
          type="button"
          className="sidebar-collapse"
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
        </button>
        <nav id="primary-navigation" aria-label="Primary navigation">
          {navSections.map((section) => (
            <div className="sidebar__nav-section" key={section.label}>
              <span className="sidebar__section">{section.label}</span>
              {section.items.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  className={activePage === id ? "nav-item nav-item--active" : "nav-item"}
                  type="button"
                  aria-current={activePage === id ? "page" : undefined}
                  aria-label={label}
                  title={collapsed ? label : undefined}
                  onClick={() => navigate(id)}
                >
                  <Icon aria-hidden="true" size={18} />
                  <span>{label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>

        <section className="module-readiness" aria-label="Connected intelligence workflow">
          <div><Network aria-hidden="true" size={17} /><span><strong>One connected workflow</strong><small>From camera to case</small></span></div>
          <p>Connect. Detect. Investigate.</p>
        </section>

        <div className="sidebar__footer">
          <div className="security-tile">
            <ShieldCheck aria-hidden="true" size={18} />
            <span><strong>Gujarat operations</strong><small>Federated intelligence</small></span>
          </div>
          <div className="api-state">
            <i className={apiConnected === null ? "api-state__dot api-state__dot--pending" : apiConnected ? "api-state__dot" : "api-state__dot api-state__dot--down"} />
            <span>{apiConnected === null ? "Connecting" : apiConnected ? "Registry API connected" : "Registry API unavailable"}</span>
          </div>
        </div>
      </aside>

      {mobileNavOpen ? <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} /> : null}

      <div className="application-frame">
        <header className="command-topbar">
          <div className="command-topbar__identity">
            <span className="command-topbar__eyebrow">{pageMeta[activePage].eyebrow}</span>
            <div>
              <strong>{pageMeta[activePage].label}</strong>
            </div>
          </div>
          <div className="command-topbar__posture" aria-label="Live platform status">
            <TopMetric icon={Network} label="Registry" value={apiConnected ? "Connected" : apiConnected === false ? "Unavailable" : "Connecting"} tone={apiConnected ? "healthy" : apiConnected === false ? "critical" : "pending"} />
            <TopMetric icon={Camera} label="Online cameras" value={statistics ? statistics.online.toLocaleString("en-IN") : "—"} />
            <TopMetric icon={BrainCircuit} label="Reachable probes" value={federationConnected ? (federationStatistics?.reachable ?? 0).toLocaleString("en-IN") : federationConnected === false ? "Pending" : "Connecting"} tone={federationConnected ? "healthy" : federationConnected === false ? "pending" : undefined} />
          </div>
          <button className="topbar-alert-link" type="button" title="Open watchlist alerts" aria-label="Open watchlist alerts" onClick={() => navigate("alerts")}><BellRing aria-hidden="true" size={18} /></button>
          <ThemeToggle theme={theme} onToggle={() => setTheme((value) => value === "dark" ? "light" : "dark")} />
        </header>
        <main id="main-content" tabIndex={-1} className="main-content">{children}</main>
      </div>
    </div>
  );
}

function ThemeToggle({
  theme,
  onToggle,
  compact = false,
}: {
  theme: Theme;
  onToggle: () => void;
  compact?: boolean;
}) {
  const nextTheme = theme === "dark" ? "light" : "dark";
  const Icon = theme === "dark" ? Sun : Moon;
  return (
    <button
      type="button"
      className={`theme-toggle${compact ? " theme-toggle--compact" : ""}`}
      aria-label={`Switch to ${nextTheme} theme`}
      title={`Switch to ${nextTheme} theme`}
      onClick={onToggle}
    >
      <Icon aria-hidden="true" size={17} />
      {compact ? null : <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>}
    </button>
  );
}

function TopMetric({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Network;
  label: string;
  value: string;
  tone?: "healthy" | "critical" | "pending";
}) {
  return (
    <div className={`topbar-metric${tone ? ` topbar-metric--${tone}` : ""}`}>
      <Icon aria-hidden="true" size={16} />
      <span><small>{label}</small><strong>{value}</strong></span>
    </div>
  );
}

function Brand({ compact = false, collapsed = false }: { compact?: boolean; collapsed?: boolean }) {
  return (
    <div className={`brand${compact ? " brand--compact" : ""}${collapsed ? " brand--collapsed" : ""}`}>
      <span className="brand-symbol" aria-hidden="true"><img src="/assets/drishti-ai-logo-transparent.png" alt="" /></span>
      <span className="brand-wordmark"><strong>Drashti<span>AI</span></strong><small>INTELLIGENCE IN SIGHT</small></span>
    </div>
  );
}
