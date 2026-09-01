import {
  Activity,
  BrainCircuit,
  Camera,
  CircleAlert,
  RadioTower,
} from "lucide-react";
import type { CameraStatistics } from "../types/registry";

interface SummaryCardsProps {
  statistics: CameraStatistics | null;
  loading: boolean;
}

const cards = [
  { key: "total", label: "Registered assets", note: "Statewide inventory", icon: Camera, tone: "cyan" },
  { key: "online", label: "Online now", note: "Heartbeat confirmed", icon: RadioTower, tone: "green" },
  { key: "offline", label: "Offline", note: "Requires attention", icon: CircleAlert, tone: "red" },
  { key: "degraded", label: "Degraded", note: "Service impaired", icon: Activity, tone: "amber" },
  { key: "ai_enabled", label: "AI enabled", note: "Analytics capable", icon: BrainCircuit, tone: "violet" },
] as const;

export function SummaryCards({ statistics, loading }: SummaryCardsProps) {
  return (
    <section className="summary-grid" aria-label="Registry summary">
      {cards.map(({ key, label, note, icon: Icon, tone }) => {
        const value = statistics?.[key];
        const percentage =
          statistics && statistics.total > 0 && key !== "total"
            ? Math.round(((value ?? 0) / statistics.total) * 100)
            : null;
        return (
          <article className={`summary-card summary-card--${tone}`} key={key}>
            <span className="summary-card__icon"><Icon aria-hidden="true" size={20} /></span>
            <div className="summary-card__content">
              <div className="summary-card__topline">
                <span>{label}</span>
                {percentage !== null ? <small>{percentage}%</small> : null}
              </div>
              {loading ? <span className="skeleton skeleton--number" /> : <strong>{value?.toLocaleString("en-IN") ?? "—"}</strong>}
              <small>{note}</small>
            </div>
          </article>
        );
      })}
    </section>
  );
}
