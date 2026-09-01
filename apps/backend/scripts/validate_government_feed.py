"""Run one secret-safe, end-to-end decode against an onboarded government feed."""

from __future__ import annotations

import argparse
import json
import logging
import time

from fastapi.testclient import TestClient

from app.main import app

logging.disable(logging.CRITICAL)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera-code", default="GOV-LIVE-1")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--adapter", choices=("auto", "rtsp", "hls"), default="auto")
    parser.add_argument("--verbose", action="store_true")
    arguments = parser.parse_args()

    with TestClient(app) as client:
        camera_page = client.get(
            "/api/v1/cameras",
            params={"search": arguments.camera_code, "page_size": 100},
        )
        camera_page.raise_for_status()
        camera = next(
            (
                item
                for item in camera_page.json()["items"]
                if item["camera_code"] == arguments.camera_code
            ),
            None,
        )
        if camera is None:
            print(json.dumps({"status": "not_onboarded", "camera": arguments.camera_code}))
            return 2

        start_payload: dict[str, object] = {
            "transport": "tcp",
            "decode_fps": 8,
            "target_fps": 6,
        }
        if arguments.adapter != "auto":
            connections = client.get(
                "/api/v1/federation/connections",
                params={"camera_id": camera["id"], "page_size": 20},
            )
            connections.raise_for_status()
            profile = next(
                (
                    item
                    for item in connections.json()["items"]
                    if item["adapter_kind"] == arguments.adapter
                ),
                None,
            )
            if profile is None:
                print(
                    json.dumps(
                        {
                            "status": "adapter_not_onboarded",
                            "camera": arguments.camera_code,
                            "adapter": arguments.adapter,
                        }
                    )
                )
                return 2
            start_payload["connection_id"] = profile["id"]
        start = client.post(
            f"/api/v1/streams/{camera['id']}/start",
            json=start_payload,
        )
        start.raise_for_status()
        health = start.json()
        last_state = health["state"]
        if arguments.verbose:
            print(json.dumps({"event": "state", "state": last_state}), flush=True)
        deadline = time.monotonic() + max(1.0, arguments.timeout)
        while time.monotonic() < deadline and health["state"] not in {"streaming", "failed"}:
            time.sleep(0.5)
            response = client.get(f"/api/v1/streams/{camera['id']}/health")
            response.raise_for_status()
            health = response.json()
            if arguments.verbose and health["state"] != last_state:
                last_state = health["state"]
                print(
                    json.dumps(
                        {
                            "event": "state",
                            "state": last_state,
                            "adapter": (health.get("profile") or {}).get("adapter_kind"),
                            "failovers": (health.get("metrics") or {}).get(
                                "source_failover_count", 0
                            ),
                        }
                    ),
                    flush=True,
                )

        preview = None
        if health["state"] == "streaming":
            preview = app.state.stream_engine.latest_jpeg(camera["id"], timeout=5)
        stop = client.post(f"/api/v1/streams/{camera['id']}/stop")
        stop.raise_for_status()
        metrics = health.get("metrics") or {}
        print(
            json.dumps(
                {
                    "camera": camera["camera_code"],
                    "state": health["state"],
                    "adapter": (health.get("profile") or {}).get("adapter_kind"),
                    "decoded_fps": round(metrics.get("decoded_fps") or 0, 2),
                    "pts_timing_active": metrics.get("pts_timing_active", False),
                    "source_pts_seconds": metrics.get("latest_source_pts_seconds"),
                    "transport_failovers": metrics.get("source_failover_count", 0),
                    "preview_jpeg_bytes": len(preview[1]) if preview else 0,
                    "stop_state": stop.json()["state"],
                    "error_code": health.get("last_error_code"),
                },
                separators=(",", ":"),
            )
        )
        return 0 if health["state"] == "streaming" and preview else 1


if __name__ == "__main__":
    raise SystemExit(main())
