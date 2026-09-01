from __future__ import annotations

import http.client
import json
import re
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, RegistryError
from app.federation import AdapterRegistry, EndpointCipher
from app.federation.adapters import _HttpAdapter
from app.federation.network import NetworkPolicy
from app.models import AuditLog, Camera, ConnectionProfile, Department
from app.schemas.government_feeds import (
    GovernmentFeedCatalogueRead,
    GovernmentFeedRead,
    GovernmentFeedSyncRead,
    GovernmentFeedSyncRequest,
)

SOURCE_SYSTEM = "government-evaluation-catalogue"
DEPARTMENT_CODE = "GOV-EVAL"
DEPARTMENT_NAME = "Government Evaluation Feed Grid"
PRIMARY_PROFILE_NAME = "Catalogue RTSP primary"
FALLBACK_PROFILE_NAME = "Catalogue HLS fallback"
MAX_CATALOGUE_BYTES = 512 * 1024


class _CatalogueCamera(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    number: int = Field(ge=0, le=1_000_000)
    name: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=500)
    codec: str = Field(default="", max_length=40)
    live: bool
    width: int = Field(default=0, ge=0, le=16_384)
    height: int = Field(default=0, ge=0, le=16_384)
    fps: float = Field(default=0, ge=0, le=240)
    bitrate_kbps: int = Field(default=0, ge=0, le=1_000_000)
    rtsp_url: SecretStr
    hls_live_url: SecretStr


class _CataloguePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cameras: list[_CatalogueCamera]


@dataclass(frozen=True, slots=True)
class _Region:
    district: str
    city: str | None
    latitude: float
    longitude: float
    accuracy: str


_REGIONS: tuple[tuple[tuple[str, ...], _Region], ...] = (
    (("bilimora",), _Region("Navsari", "Bilimora", 20.7696, 72.9613, "city_centroid")),
    (
        ("khaparia", "gandevi", "tankal"),
        _Region("Navsari", None, 20.9467, 72.9520, "district_centroid"),
    ),
    (("gandhidham",), _Region("Kutch", "Gandhidham", 23.0753, 70.1337, "city_centroid")),
    (
        ("junagadh", "timbavadi", "majewadi", "dolatpara"),
        _Region("Junagadh", "Junagadh", 21.5222, 70.4579, "city_centroid"),
    ),
    (
        ("gir-somnath", "somnath"),
        _Region("Gir Somnath", None, 20.9159, 70.3629, "district_centroid"),
    ),
    (("rajkot",), _Region("Rajkot", "Rajkot", 22.3039, 70.8022, "city_centroid")),
    (("patan",), _Region("Patan", "Patan", 23.8493, 72.1266, "city_centroid")),
    (("mervada",), _Region("Banaskantha", None, 24.1725, 72.4387, "district_centroid")),
    (("adalaj", "dehgam"), _Region("Gandhinagar", None, 23.2156, 72.6369, "district_centroid")),
    (
        ("chiman", "janpath", "o.n.g.c", "ongc", "paldi", "visat", "cn vidhyalaya", "suvidha"),
        _Region("Ahmedabad", "Ahmedabad", 23.0225, 72.5714, "city_centroid"),
    ),
)


class GovernmentFeedCatalogueClient:
    """Bounded, DNS-pinned reader for a configured government feed catalogue."""

    def __init__(
        self,
        *,
        catalogue_url: str | None,
        allowed_cidrs: tuple[str, ...],
        timeout_seconds: float,
        max_items: int,
    ) -> None:
        self.catalogue_url = catalogue_url
        self.policy = NetworkPolicy(allowed_cidrs)
        self.timeout_seconds = timeout_seconds
        self.max_items = max_items

    def fetch(self) -> tuple[datetime, list[_CatalogueCamera]]:
        if not self.catalogue_url:
            raise RegistryError(
                code="GOVERNMENT_FEED_CATALOGUE_NOT_CONFIGURED",
                message="The government feed catalogue is not configured on this deployment",
                status_code=503,
            )
        target = self.policy.validate_network_endpoint(
            self.catalogue_url,
            allowed_schemes=("https",),
            default_ports={"https": 443},
        )
        try:
            status_code, content_type, body = _HttpAdapter._pinned_request(
                self.catalogue_url,
                target=target,
                timeout_seconds=self.timeout_seconds,
                method="GET",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Drishti-AI-Government-Catalogue/1.0",
                },
                body=None,
                response_prefix_limit=MAX_CATALOGUE_BYTES + 1,
            )
            if status_code != 200 or "json" not in content_type:
                raise ValueError("catalogue response contract mismatch")
            if len(body) > MAX_CATALOGUE_BYTES:
                raise ValueError("catalogue response exceeded size limit")
            payload = _CataloguePayload.model_validate_json(body)
        except (
            OSError,
            TimeoutError,
            ssl.SSLError,
            http.client.HTTPException,
            UnicodeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise RegistryError(
                code="GOVERNMENT_FEED_CATALOGUE_UNAVAILABLE",
                message="The government feed catalogue could not be read or validated",
                status_code=502,
            ) from exc
        if not payload.cameras or len(payload.cameras) > self.max_items:
            raise RegistryError(
                code="GOVERNMENT_FEED_CATALOGUE_INVALID",
                message="The government feed catalogue item count is outside the configured limit",
                status_code=502,
            )
        ids = [camera.id for camera in payload.cameras]
        if len(ids) != len(set(ids)):
            raise RegistryError(
                code="GOVERNMENT_FEED_CATALOGUE_INVALID",
                message="The government feed catalogue contains duplicate camera identifiers",
                status_code=502,
            )
        return datetime.now(UTC), sorted(payload.cameras, key=lambda item: (item.number, item.id))


class GovernmentFeedService:
    def __init__(
        self,
        session: Session,
        *,
        client: GovernmentFeedCatalogueClient,
        adapters: AdapterRegistry,
        cipher: EndpointCipher,
        rtsp_hosts: tuple[str, ...] = (),
        fallback_latitude: float,
        fallback_longitude: float,
        actor_id: str,
        request_id: str | None,
    ) -> None:
        self.session = session
        self.client = client
        self.adapters = adapters
        self.cipher = cipher
        self.rtsp_hosts = frozenset(host.casefold() for host in rtsp_hosts)
        self.fallback_latitude = fallback_latitude
        self.fallback_longitude = fallback_longitude
        self.actor_id = actor_id
        self.request_id = request_id

    def catalogue(self) -> GovernmentFeedCatalogueRead:
        if not self.client.catalogue_url:
            return GovernmentFeedCatalogueRead(
                configured=False,
                provider=DEPARTMENT_NAME,
                fetched_at=None,
                total=0,
                live=0,
                h264=0,
                h265=0,
                metadata_pending=0,
                items=[],
            )
        fetched_at, entries = self.client.fetch()
        items = self._read_items(entries)
        codecs = [self._codec(entry.codec) for entry in entries]
        return GovernmentFeedCatalogueRead(
            configured=True,
            provider=DEPARTMENT_NAME,
            fetched_at=fetched_at,
            total=len(entries),
            live=sum(entry.live for entry in entries),
            h264=sum(codec == "h264" for codec in codecs),
            h265=sum(codec == "h265" for codec in codecs),
            metadata_pending=sum(codec is None for codec in codecs),
            items=items,
        )

    def sync(self, request: GovernmentFeedSyncRequest) -> GovernmentFeedSyncRead:
        if not self.cipher.available:
            self.cipher.encrypt("")
        fetched_at, discovered = self.client.fetch()
        entries = [entry for entry in discovered if request.include_offline or entry.live]
        prepared = [self._validated_endpoints(entry) for entry in entries]
        department = self._department()
        camera_counts = {"created": 0, "updated": 0, "unchanged": 0}
        connection_counts = {"created": 0, "updated": 0, "unchanged": 0}
        provisional = 0

        try:
            for entry, rtsp_endpoint, hls_endpoint in prepared:
                camera, camera_state, is_provisional = self._upsert_camera(department, entry)
                camera_counts[camera_state] += 1
                provisional += int(is_provisional)
                self.session.flush()
                primary, primary_state = self._upsert_profile(
                    camera,
                    entry,
                    name=PRIMARY_PROFILE_NAME,
                    adapter_kind="rtsp",
                    stream_role="primary",
                    endpoint=rtsp_endpoint,
                    priority=10,
                )
                connection_counts[primary_state] += 1
                if request.create_hls_fallback:
                    _, fallback_state = self._upsert_profile(
                        camera,
                        entry,
                        name=FALLBACK_PROFILE_NAME,
                        adapter_kind="hls",
                        stream_role="playback",
                        endpoint=hls_endpoint,
                        priority=50,
                    )
                    connection_counts[fallback_state] += 1
                camera.stream_reference = f"connection-profile:{primary.id}"
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(
                "GOVERNMENT_FEED_SYNC_CONFLICT",
                "The catalogue changed while government feeds were being synchronized",
            ) from exc

        items = self._read_items(entries)
        return GovernmentFeedSyncRead(
            provider=DEPARTMENT_NAME,
            fetched_at=fetched_at,
            discovered=len(entries),
            live=sum(entry.live for entry in entries),
            cameras_created=camera_counts["created"],
            cameras_updated=camera_counts["updated"],
            cameras_unchanged=camera_counts["unchanged"],
            connections_created=connection_counts["created"],
            connections_updated=connection_counts["updated"],
            connections_unchanged=connection_counts["unchanged"],
            provisional_geospatial_records=provisional,
            items=items,
        )

    def _department(self) -> Department:
        department = self.session.scalar(
            select(Department).where(Department.code == DEPARTMENT_CODE)
        )
        if department:
            return department
        department = Department(
            code=DEPARTMENT_CODE,
            name=DEPARTMENT_NAME,
            description=(
                "Dynamically discovered government challenge feeds. Locations are imported from "
                "the provider catalogue; coordinates remain provisional until GIS verification."
            ),
        )
        self.session.add(department)
        self.session.flush()
        self._audit(
            resource_type="department",
            resource_id=department.id,
            action="government_catalogue.department_created",
            changes={"code": DEPARTMENT_CODE},
        )
        return department

    def _upsert_camera(
        self, department: Department, entry: _CatalogueCamera
    ) -> tuple[Camera, str, bool]:
        camera = self.session.scalar(
            select(Camera)
            .options(selectinload(Camera.department))
            .where(Camera.source_system == SOURCE_SYSTEM, Camera.external_id == entry.id)
        )
        region = self._region(entry.location)
        provisional = True
        metadata = self._camera_metadata(entry, region)
        if camera is None:
            camera = Camera(
                camera_code=self._camera_code(entry.id),
                camera_name=self._camera_name(entry),
                department=department,
                district=region.district,
                city=region.city,
                location_description=entry.location,
                latitude=region.latitude,
                longitude=region.longitude,
                camera_type="fixed",
                vendor="Government feed gateway",
                vms="Federated evaluation gateway",
                connectivity_type="broadband",
                stream_protocol="rtsp",
                rtsp_capable=True,
                onvif_capable=False,
                status="active" if entry.live else "inactive",
                health="online" if entry.live else "offline",
                last_heartbeat=datetime.now(UTC),
                health_details={"source": "provider_catalogue", "reported_live": entry.live},
                ownership="government",
                owner_name=DEPARTMENT_NAME,
                is_public_facing=True,
                ai_capabilities=["vehicle_detection", "vehicle_tracking", "anpr"],
                ai_enabled=True,
                tags=["government-evaluation", "catalogue-discovered", "mixed-codec"],
                installation_metadata=metadata,
                source_system=SOURCE_SYSTEM,
                external_id=entry.id,
            )
            self.session.add(camera)
            self.session.flush()
            self._audit(
                resource_type="camera",
                resource_id=camera.id,
                action="government_catalogue.camera_created",
                changes={"external_id": entry.id, "live": entry.live},
            )
            return camera, "created", provisional

        existing_metadata = camera.installation_metadata or {}
        provisional = bool(existing_metadata.get("coordinates_provisional", False))
        changes: dict[str, object] = {}
        values: dict[str, object] = {
            "camera_name": self._camera_name(entry),
            "location_description": entry.location,
            "status": "active" if entry.live else "inactive",
            "health": "online" if entry.live else "offline",
            "last_heartbeat": datetime.now(UTC),
            "health_details": {"source": "provider_catalogue", "reported_live": entry.live},
            "installation_metadata": {**existing_metadata, **metadata},
        }
        if provisional:
            values.update(
                district=region.district,
                city=region.city,
                latitude=region.latitude,
                longitude=region.longitude,
            )
        for field, value in values.items():
            previous = getattr(camera, field)
            if field == "last_heartbeat" or previous != value:
                setattr(camera, field, value)
                if field != "last_heartbeat":
                    changes[field] = {"old": previous, "new": value}
        if changes:
            self._audit(
                resource_type="camera",
                resource_id=camera.id,
                action="government_catalogue.camera_updated",
                changes={"fields": sorted(changes), "external_id": entry.id},
            )
            return camera, "updated", provisional
        return camera, "unchanged", provisional

    def _upsert_profile(
        self,
        camera: Camera,
        entry: _CatalogueCamera,
        *,
        name: str,
        adapter_kind: str,
        stream_role: str,
        endpoint: str,
        priority: int,
    ) -> tuple[ConnectionProfile, str]:
        profile = self.session.scalar(
            select(ConnectionProfile).where(
                ConnectionProfile.camera_id == camera.id,
                ConnectionProfile.name == name,
                ConnectionProfile.stream_role == stream_role,
            )
        )
        adapter = self.adapters.get(adapter_kind)
        fingerprint = self.cipher.fingerprint(endpoint)
        metadata = {
            "managed_by": SOURCE_SYSTEM,
            "catalogue_external_id": entry.id,
            "catalogue_live": entry.live,
            "codec": self._codec(entry.codec) or "pending",
            "width": entry.width,
            "height": entry.height,
            "source_fps": entry.fps,
            "bitrate_kbps": entry.bitrate_kbps,
            "transport": "tcp" if adapter_kind == "rtsp" else "https",
        }
        if profile is None:
            profile = ConnectionProfile(
                camera=camera,
                name=name,
                adapter_kind=adapter_kind,
                stream_role=stream_role,
                endpoint_ciphertext=self.cipher.encrypt(endpoint),
                endpoint_display=adapter.endpoint_display(endpoint),
                endpoint_fingerprint=fingerprint,
                encryption_key_id=self.cipher.key_id,
                enabled=True,
                priority=priority,
                verification_status="unverified",
                normalized_metadata=metadata,
                created_by=self.actor_id,
            )
            self.session.add(profile)
            self.session.flush()
            self._audit(
                resource_type="connection_profile",
                resource_id=profile.id,
                action="government_catalogue.connection_created",
                changes={
                    "camera_id": camera.id,
                    "adapter_kind": adapter_kind,
                    "stream_role": stream_role,
                },
            )
            return profile, "created"

        changed_fields: list[str] = []
        if (
            profile.endpoint_fingerprint != fingerprint
            or profile.encryption_key_id != self.cipher.key_id
        ):
            profile.endpoint_ciphertext = self.cipher.encrypt(endpoint)
            profile.endpoint_display = adapter.endpoint_display(endpoint)
            profile.endpoint_fingerprint = fingerprint
            profile.encryption_key_id = self.cipher.key_id
            profile.verification_status = "unverified"
            profile.last_error_code = None
            profile.last_error_message = None
            changed_fields.append("endpoint")
        for field, value in {
            "adapter_kind": adapter_kind,
            "priority": priority,
            "normalized_metadata": metadata,
        }.items():
            if getattr(profile, field) != value:
                setattr(profile, field, value)
                changed_fields.append(field)
        if changed_fields:
            self._audit(
                resource_type="connection_profile",
                resource_id=profile.id,
                action="government_catalogue.connection_updated",
                changes={"fields": sorted(changed_fields), "camera_id": camera.id},
            )
            return profile, "updated"
        return profile, "unchanged"

    def _validated_endpoints(self, entry: _CatalogueCamera) -> tuple[_CatalogueCamera, str, str]:
        catalogue = urlsplit(self.client.catalogue_url or "")
        rtsp = entry.rtsp_url.get_secret_value().strip()
        rtsp_parts = urlsplit(rtsp)
        catalogue_host = (catalogue.hostname or "").casefold()
        rtsp_host = (rtsp_parts.hostname or "").casefold()
        allowed_rtsp_hosts = self.rtsp_hosts or frozenset({catalogue_host})
        if rtsp_host not in allowed_rtsp_hosts:
            raise RegistryError(
                code="GOVERNMENT_FEED_CATALOGUE_INVALID",
                message="A catalogue stream endpoint does not belong to the configured provider",
                status_code=502,
            )
        self.adapters.get("rtsp").validate_endpoint(rtsp)

        raw_hls = entry.hls_live_url.get_secret_value().strip()
        hls = urljoin(self.client.catalogue_url or "", raw_hls)
        hls_parts = urlsplit(hls)
        if hls_parts.hostname != catalogue.hostname:
            raise RegistryError(
                code="GOVERNMENT_FEED_CATALOGUE_INVALID",
                message="A catalogue fallback endpoint does not belong to the configured provider",
                status_code=502,
            )
        if catalogue.scheme == "https" and hls_parts.scheme == "http":
            hls = urlunsplit(("https", hls_parts.netloc, hls_parts.path, hls_parts.query, ""))
        self.adapters.get("hls").validate_endpoint(hls)
        return entry, rtsp, hls

    def _read_items(self, entries: list[_CatalogueCamera]) -> list[GovernmentFeedRead]:
        external_ids = [entry.id for entry in entries]
        cameras = (
            list(
                self.session.scalars(
                    select(Camera)
                    .where(
                        Camera.source_system == SOURCE_SYSTEM, Camera.external_id.in_(external_ids)
                    )
                    .order_by(Camera.camera_code)
                )
            )
            if external_ids
            else []
        )
        by_external = {camera.external_id: camera for camera in cameras}
        camera_ids = [camera.id for camera in cameras]
        profiles = (
            list(
                self.session.scalars(
                    select(ConnectionProfile).where(ConnectionProfile.camera_id.in_(camera_ids))
                )
            )
            if camera_ids
            else []
        )
        profile_map = {(profile.camera_id, profile.name): profile for profile in profiles}
        items: list[GovernmentFeedRead] = []
        for entry in entries:
            camera = by_external.get(entry.id)
            primary = profile_map.get((camera.id, PRIMARY_PROFILE_NAME)) if camera else None
            fallback = profile_map.get((camera.id, FALLBACK_PROFILE_NAME)) if camera else None
            sync_state = "new" if camera is None else "onboarded" if primary else "incomplete"
            items.append(
                GovernmentFeedRead(
                    external_id=entry.id,
                    number=entry.number,
                    name=entry.name,
                    location=entry.location,
                    live=entry.live,
                    codec=self._codec(entry.codec),
                    width=entry.width or None,
                    height=entry.height or None,
                    fps=entry.fps or None,
                    bitrate_kbps=entry.bitrate_kbps or None,
                    camera_id=camera.id if camera else None,
                    camera_code=camera.camera_code if camera else None,
                    primary_connection_id=primary.id if primary else None,
                    fallback_connection_id=fallback.id if fallback else None,
                    sync_state=sync_state,
                )
            )
        return items

    def _region(self, location: str) -> _Region:
        normalized = location.casefold()
        for keywords, region in _REGIONS:
            if any(keyword in normalized for keyword in keywords):
                return region
        return _Region(
            "Location Pending Survey",
            None,
            self.fallback_latitude,
            self.fallback_longitude,
            "state_fallback",
        )

    @staticmethod
    def _camera_code(external_id: str) -> str:
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", external_id).strip("-").upper()
        return f"GOV-LIVE-{safe_id}"[:64]

    @staticmethod
    def _camera_name(entry: _CatalogueCamera) -> str:
        location = re.sub(r"^\s*\d+\s*", "", entry.location).strip(" -")
        return location or entry.name

    @staticmethod
    def _codec(codec: str) -> str | None:
        normalized = codec.casefold().strip()
        if normalized in {"hevc", "h265", "h.265"}:
            return "h265"
        if normalized in {"avc", "h264", "h.264"}:
            return "h264"
        return normalized or None

    def _camera_metadata(self, entry: _CatalogueCamera, region: _Region) -> dict[str, object]:
        return {
            "catalogue_location": entry.location,
            "catalogue_codec": self._codec(entry.codec) or "pending",
            "catalogue_width": entry.width,
            "catalogue_height": entry.height,
            "catalogue_fps": entry.fps,
            "catalogue_bitrate_kbps": entry.bitrate_kbps,
            "geospatial_accuracy": region.accuracy,
            "coordinates_provisional": True,
            "geospatial_note": "Replace centroid coordinates after department GIS verification",
        }

    def _audit(
        self,
        *,
        resource_type: str,
        resource_id: str,
        action: str,
        changes: dict[str, object],
    ) -> None:
        self.session.add(
            AuditLog(
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                actor_id=self.actor_id,
                request_id=self.request_id,
                source="government_catalogue",
                changes=json.loads(json.dumps(changes, default=str)),
            )
        )
