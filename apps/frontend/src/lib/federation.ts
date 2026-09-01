import type { FederationAdapter, FederationConnection } from "../types/federation";

const reachableTokens = ["reachable", "verified", "healthy", "ready"];
const attentionTokens = ["unreachable", "failed", "error", "degraded", "timeout", "authentication_required", "blocked", "misconfigured", "adapter_unavailable"];
const pendingTokens = ["unverified", "pending", "unknown", "not_tested", "never_probed"];

export type FederationStatusTone = "reachable" | "attention" | "pending" | "neutral";

export const federationStatusTone = (status?: string | null): FederationStatusTone => {
  const value = (status ?? "unknown").toLowerCase();
  if (value.includes("disabled")) return "neutral";
  if (attentionTokens.some((token) => value.includes(token))) return "attention";
  if (reachableTokens.some((token) => value.includes(token))) return "reachable";
  if (pendingTokens.some((token) => value.includes(token))) return "pending";
  return "neutral";
};

export const adapterIsAvailable = (adapter: FederationAdapter): boolean => {
  if (typeof adapter.availability === "boolean") return adapter.availability;
  return !["unavailable", "disabled", "missing", "false"].includes(adapter.availability.toLowerCase());
};

const maskHostname = (hostname: string): string => {
  if (/[\u2022*]|(?:^|\.)x(?:\.|$)|…/.test(hostname)) return hostname;
  if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(hostname)) {
    const [first, second] = hostname.split(".");
    return `${first}.${second}.x.x`;
  }
  if (hostname.includes(":")) {
    const unwrapped = hostname.replace(/^\[|\]$/g, "");
    return `[${unwrapped.split(":").filter(Boolean).slice(0, 2).join(":")}::]`;
  }
  return hostname.split(".").map((label) => label.length <= 2 ? "*" : `${label[0]}***${label.at(-1)}`).join(".");
};

export const safeEndpointDisplay = (value?: string | null): string => {
  if (!value) return "Endpoint secured";
  const trimmed = value.trim();
  try {
    const parsed = new URL(trimmed);
    const port = parsed.port ? `:${parsed.port}` : "";
    return `${parsed.protocol}//${maskHostname(parsed.hostname)}${port}/••••`;
  } catch {
    const scheme = trimmed.match(/^([a-z][a-z0-9+.-]*):\/\//i)?.[1];
    return scheme ? `${scheme.toLowerCase()}://secured/••••` : "Endpoint secured";
  }
};

export const validateFederationEndpoint = (endpoint: string, adapter?: FederationAdapter): string | null => {
  if (!endpoint.trim()) return "A source endpoint is required.";
  if (/\s/.test(endpoint)) return "Endpoints cannot contain spaces.";
  try {
    const parsed = new URL(endpoint);
    const scheme = parsed.protocol.replace(":", "").toLowerCase();
    if (scheme === "file") {
      if (!parsed.pathname || parsed.pathname === "/") return "Enter a complete recorded-file path.";
    } else if (!parsed.hostname) return "Enter a hostname or IP address.";
    if (parsed.username || parsed.password) return "Do not embed usernames or passwords. Use an opaque credential reference.";
    if (adapter?.schemes?.length && !adapter.schemes.map((item) => item.replace(":", "").toLowerCase()).includes(scheme)) {
      return `${adapter.label} accepts ${adapter.schemes.join(", ")} endpoints.`;
    }
    return null;
  } catch {
    return "Enter a complete endpoint including its protocol, for example rtsp://gateway.example/stream.";
  }
};

const sensitiveKey = /(password|passwd|secret|token|credential|endpoint|uri|url|key_material)/i;
const looksSensitiveValue = (value: string): boolean =>
  /:\/\//.test(value) || /(?:bearer|basic)\s+[a-z0-9._~+/=-]+/i.test(value);

export const safeMetadata = (metadata?: Record<string, unknown> | null): Array<[string, string]> => {
  if (!metadata) return [];
  return Object.entries(metadata).map(([key, value]) => {
    if (sensitiveKey.test(key)) return [key, "Redacted"];
    if (["string", "number", "boolean"].includes(typeof value)) {
      const rendered = String(value);
      return [key, looksSensitiveValue(rendered) ? "Redacted" : rendered.slice(0, 160)];
    }
    if (value === null) return [key, "—"];
    return [key, "Structured metadata"];
  });
};

export const connectionLocation = (connection: FederationConnection): string =>
  [connection.city, connection.district].filter(Boolean).join(", ") || "Location unavailable";

export const safeRuntimePlaylistUrl = (value?: string | null, origin?: string): string | null => {
  if (!value) return null;
  const trustedOrigin = origin ?? (typeof window === "undefined" ? "http://localhost" : window.location.origin);
  try {
    const parsed = new URL(value, trustedOrigin);
    const expected = new URL(trustedOrigin);
    if (parsed.origin !== expected.origin || !["http:", "https:"].includes(parsed.protocol)) return null;
    if (parsed.username || parsed.password || parsed.hash) return null;
    if (/%2f|%5c/i.test(parsed.pathname)) return null;
    if (!parsed.pathname.includes("/federation/runtime/") || !parsed.pathname.toLowerCase().endsWith(".m3u8")) return null;
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return null;
  }
};
