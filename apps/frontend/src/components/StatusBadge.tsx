import { Activity, CircleDot, RadioTower } from "lucide-react";
import { titleCase } from "../lib/format";

interface StatusBadgeProps {
  value?: string | null;
  kind?: "health" | "lifecycle" | "capability";
  pulse?: boolean;
}

export function StatusBadge({ value, kind = "health", pulse = false }: StatusBadgeProps) {
  const normalized = (value || "unknown").toLowerCase();
  const Icon = kind === "health" ? RadioTower : kind === "capability" ? Activity : CircleDot;
  return (
    <span className={`status-badge status-badge--${kind} status-badge--${normalized}`}>
      <Icon aria-hidden="true" size={12} />
      <span>{titleCase(normalized)}</span>
      {pulse && normalized === "online" ? <span className="status-pulse" aria-hidden="true" /> : null}
    </span>
  );
}
