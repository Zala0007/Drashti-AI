import { Activity, CircleOff, Clock3, LoaderCircle, OctagonAlert, Radio, RotateCcw } from "lucide-react";
import { titleCase } from "../lib/format";

export type RuntimeTone = "live" | "starting" | "warning" | "stopped" | "failed";

const runtimeTone = (state?: string | null): RuntimeTone => {
  const normalized = (state ?? "unavailable").toLowerCase();
  if (normalized === "live") return "live";
  if (normalized === "starting") return "starting";
  if (["degraded", "backoff"].includes(normalized)) return "warning";
  if (normalized === "stopped") return "stopped";
  return "failed";
};

export function RuntimeStatusBadge({ state }: { state?: string | null }) {
  const tone = runtimeTone(state);
  const Icon = tone === "live"
    ? Radio
    : tone === "starting"
      ? LoaderCircle
      : tone === "warning"
        ? state === "backoff" ? RotateCcw : Activity
        : tone === "stopped"
          ? CircleOff
          : state === "unavailable" ? Clock3 : OctagonAlert;
  return (
    <span className={`runtime-status runtime-status--${tone}`}>
      <Icon className={tone === "starting" ? "spin" : undefined} aria-hidden="true" size={14} />
      <span>{titleCase(state ?? "unavailable")}</span>
    </span>
  );
}
