import type { Camera, HealthStatus } from "../types/registry";

export const titleCase = (value?: string | null): string => {
  if (!value) return "—";
  return value
    .replace(/[_.-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
};

export const cameraId = (camera: Pick<Camera, "id" | "camera_uuid">): string =>
  camera.camera_uuid ?? camera.id;

export const cameraHealth = (
  camera: Pick<Camera, "health" | "health_status">,
): HealthStatus => camera.health_status ?? camera.health ?? "unknown";

export const departmentLabel = (
  camera: Pick<Camera, "department" | "department_name">,
): string => camera.department?.name ?? camera.department_name ?? "Unassigned";

export const formatTimestamp = (value?: string | null): string => {
  if (!value) return "Never reported";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Invalid timestamp";
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
};

export const relativeTime = (value?: string | null): string => {
  if (!value) return "No heartbeat";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "Unknown";
  const deltaSeconds = Math.round((timestamp - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const ranges: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, seconds] of ranges) {
    if (Math.abs(deltaSeconds) >= seconds) {
      return formatter.format(Math.round(deltaSeconds / seconds), unit);
    }
  }
  return formatter.format(deltaSeconds, "second");
};
