import { describe, expect, it } from "vitest";
import { federationStatusTone, safeEndpointDisplay, safeMetadata, safeRuntimePlaylistUrl, validateFederationEndpoint } from "./federation";

describe("federation presentation security", () => {
  it("masks raw authority and removes all endpoint path, query, and user information", () => {
    const rendered = safeEndpointDisplay("rtsp://operator:secret@10.40.18.29:554/live/camera?token=hidden");
    expect(rendered).toBe("rtsp://10.40.x.x:554/••••");
    expect(rendered).not.toMatch(/operator|secret|camera|token|hidden/);
  });

  it("redacts secret-like normalized metadata", () => {
    expect(safeMetadata({ transport: "tcp", endpoint_url: "rtsp://internal/live", access_token: "secret", width: 1920 })).toEqual([
      ["transport", "tcp"],
      ["endpoint_url", "Redacted"],
      ["access_token", "Redacted"],
      ["width", "1920"],
    ]);
  });

  it("treats disabled as neutral and authentication requirements as attention", () => {
    expect(federationStatusTone("disabled")).toBe("neutral");
    expect(federationStatusTone("authentication_required")).toBe("attention");
    expect(federationStatusTone("reachable")).toBe("reachable");
  });

  it("accepts recorded files while requiring a host for network schemes", () => {
    expect(validateFederationEndpoint("file:///approved/sample.mp4")).toBeNull();
    expect(validateFederationEndpoint("rtsp:/missing-host")).toMatch(/hostname/i);
  });

  it("allows only same-origin runtime playlists and returns a relative browser URL", () => {
    const origin = "https://command.drishti.local";
    expect(safeRuntimePlaylistUrl("/api/v1/federation/runtime/media/session-1/index.m3u8?token=opaque", origin)).toBe("/api/v1/federation/runtime/media/session-1/index.m3u8?token=opaque");
    expect(safeRuntimePlaylistUrl("https://command.drishti.local/api/v1/federation/runtime/media/session-1/index.m3u8", origin)).toBe("/api/v1/federation/runtime/media/session-1/index.m3u8");
    expect(safeRuntimePlaylistUrl("https://camera.internal/live.m3u8", origin)).toBeNull();
    expect(safeRuntimePlaylistUrl("rtsp://camera.internal/live", origin)).toBeNull();
    expect(safeRuntimePlaylistUrl("/api/v1/federation/runtime/%2e%2e%2fsecret/index.m3u8", origin)).toBeNull();
  });
});
