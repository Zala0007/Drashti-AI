"""Migrate the 30 government camera profiles to a new public gateway.

The command is a dry run unless ``--apply`` is supplied. Endpoint plaintext is
never printed, and every mutation is performed in one database transaction.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.federation import EndpointCipher, build_adapter_registry
from app.federation.security import load_or_create_development_key
from app.models import AuditLog, Camera, ConnectionProfile

CAMERA_CODE = re.compile(r"^GOV-LIVE-(\d+)$", re.IGNORECASE)


def _cipher(settings: Settings) -> EndpointCipher:
    key = settings.federation_encryption_key
    key_id = settings.federation_encryption_key_id
    if not key and settings.app_env == "development" and settings.federation_auto_development_key:
        key = load_or_create_development_key(settings.federation_development_key_file)
        key_id = "local-development-file-v1"
    return EndpointCipher(key, key_id=key_id)


def _camera_number(camera: Camera, *, count: int) -> int | None:
    match = CAMERA_CODE.fullmatch(camera.camera_code)
    if match is None:
        return None
    number = int(match.group(1))
    return number if 1 <= number <= count else None


def _reset_profile(
    profile: ConnectionProfile,
    *,
    endpoint: str,
    adapter_kind: str,
    transport: str,
    camera_endpoint_id: str,
    cipher: EndpointCipher,
    endpoint_display: str,
) -> bool:
    fingerprint = cipher.fingerprint(endpoint)
    changed = (
        profile.endpoint_fingerprint != fingerprint
        or profile.encryption_key_id != cipher.key_id
        or profile.adapter_kind != adapter_kind
    )
    metadata = {
        **(profile.normalized_metadata or {}),
        "transport": transport,
        "gateway_managed": True,
        "camera_endpoint_id": camera_endpoint_id,
    }
    if profile.normalized_metadata != metadata:
        changed = True
    if not changed:
        return False

    old_display = profile.endpoint_display
    old_fingerprint = profile.endpoint_fingerprint
    profile.adapter_kind = adapter_kind
    profile.endpoint_ciphertext = cipher.encrypt(endpoint)
    profile.endpoint_display = endpoint_display
    profile.endpoint_fingerprint = fingerprint
    profile.encryption_key_id = cipher.key_id
    profile.enabled = True
    profile.verification_status = "unverified"
    profile.last_probe_at = None
    profile.last_probe_latency_ms = None
    profile.last_error_code = None
    profile.last_error_message = None
    profile.failure_count = 0
    profile.normalized_metadata = metadata
    profile._migration_change = {  # type: ignore[attr-defined]
        "old_display": old_display,
        "new_display": endpoint_display,
        "old_fingerprint": old_fingerprint,
        "new_fingerprint": fingerprint,
    }
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="103.250.160.189")
    parser.add_argument("--rtsp-port", type=int, default=8554)
    parser.add_argument("--hls-host", default="cctv.corp8.cloud")
    parser.add_argument("--camera-count", type=int, default=30)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()

    if not 1 <= arguments.rtsp_port <= 65535:
        parser.error("--rtsp-port must be between 1 and 65535")
    if not 1 <= arguments.camera_count <= 999:
        parser.error("--camera-count must be between 1 and 999")

    settings = Settings.from_env()
    cipher = _cipher(settings)
    adapters = build_adapter_registry(
        allowed_cidrs=settings.federation_allowed_cidrs,
        media_root=settings.federation_media_root,
    )
    rtsp_adapter = adapters.get("rtsp")
    hls_adapter = adapters.get("hls")
    engine = create_engine(settings.database_url)

    summary: dict[str, object] = {
        "mode": "apply" if arguments.apply else "dry-run",
        "camera_count": 0,
        "rtsp_profiles": 0,
        "hls_profiles": 0,
        "profiles_changed": 0,
        "camera_range": None,
    }

    with Session(engine) as session:
        cameras = list(session.scalars(select(Camera).order_by(Camera.camera_code)))
        profiles = list(session.scalars(select(ConnectionProfile)))
        profiles_by_camera: dict[str, list[ConnectionProfile]] = defaultdict(list)
        for profile in profiles:
            profiles_by_camera[profile.camera_id].append(profile)

        numbered: dict[int, Camera] = {}
        for camera in cameras:
            number = _camera_number(camera, count=arguments.camera_count)
            if number is not None:
                if number in numbered:
                    raise RuntimeError(f"Duplicate government camera number {number}")
                numbered[number] = camera

        expected = set(range(1, arguments.camera_count + 1))
        if set(numbered) != expected:
            missing = sorted(expected - set(numbered))
            raise RuntimeError(
                f"Refusing partial migration: expected {arguments.camera_count} cameras; "
                f"missing numbers are {missing}"
            )

        changed_profiles: list[ConnectionProfile] = []
        for number in sorted(numbered):
            camera = numbered[number]
            camera_profiles = profiles_by_camera.get(camera.id, [])
            rtsp_profiles = [
                profile
                for profile in camera_profiles
                if profile.adapter_kind == "rtsp" and profile.stream_role == "primary"
            ]
            hls_profiles = [
                profile
                for profile in camera_profiles
                if profile.adapter_kind == "hls" and profile.stream_role == "playback"
            ]
            if len(rtsp_profiles) != 1 or len(hls_profiles) != 1:
                raise RuntimeError(
                    f"Refusing ambiguous migration for {camera.camera_code}: expected exactly "
                    "one RTSP primary and one HLS playback profile"
                )

            camera_id = f"cam{number:02d}"
            rtsp_endpoint = f"rtsp://{arguments.host}:{arguments.rtsp_port}/stream/{camera_id}"
            hls_endpoint = f"https://{arguments.hls_host}/{camera_id}/index.m3u8"
            rtsp_adapter.validate_endpoint(rtsp_endpoint)
            hls_adapter.validate_endpoint(hls_endpoint)

            primary = rtsp_profiles[0]
            fallback = hls_profiles[0]
            if _reset_profile(
                primary,
                endpoint=rtsp_endpoint,
                adapter_kind="rtsp",
                transport="tcp",
                camera_endpoint_id=camera_id,
                cipher=cipher,
                endpoint_display=rtsp_adapter.endpoint_display(rtsp_endpoint),
            ):
                changed_profiles.append(primary)
            if _reset_profile(
                fallback,
                endpoint=hls_endpoint,
                adapter_kind="hls",
                transport="https",
                camera_endpoint_id=camera_id,
                cipher=cipher,
                endpoint_display=hls_adapter.endpoint_display(hls_endpoint),
            ):
                changed_profiles.append(fallback)

            camera.stream_protocol = "rtsp"
            camera.stream_reference = f"connection-profile:{primary.id}"
            camera.rtsp_capable = True
            camera.status = "active"
            camera.ai_enabled = True

        summary.update(
            camera_count=len(numbered),
            rtsp_profiles=arguments.camera_count,
            hls_profiles=arguments.camera_count,
            profiles_changed=len(changed_profiles),
            camera_range="cam01-cam30" if arguments.camera_count == 30 else "configured",
        )

        if arguments.apply:
            for profile in changed_profiles:
                session.add(
                    AuditLog(
                        resource_type="connection_profile",
                        resource_id=profile.id,
                        action="connection.gateway_migrated",
                        actor_id="local-admin",
                        source="maintenance",
                        changes={
                            "camera_id": profile.camera_id,
                            "adapter_kind": profile.adapter_kind,
                            "endpoint": profile._migration_change,  # type: ignore[attr-defined]
                        },
                    )
                )
            session.commit()
        else:
            session.rollback()

    print(json.dumps(summary, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
