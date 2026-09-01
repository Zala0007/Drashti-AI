from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import BadRequestError, ConflictError, NotFoundError, RegistryError
from app.federation import AdapterRegistry, EndpointCipher, ProbeResult
from app.federation.security import validate_credential_reference
from app.models import AuditLog, Camera, ConnectionProfile, CredentialProfile
from app.repositories import ConnectionFilters, FederationRepository
from app.schemas.federation import (
    AdapterList,
    AdapterManifestRead,
    ConnectionAuditList,
    ConnectionCameraRead,
    ConnectionCreate,
    ConnectionList,
    ConnectionRead,
    ConnectionStatistics,
    ConnectionUpdate,
)
from app.schemas.registry import page_count

_NORMALIZED_METADATA_FIELDS = {
    "protocol",
    "status_code",
    "content_type",
    "media_type",
    "size_bytes",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalized_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Bound adapter output to the documented non-secret metadata vocabulary."""

    normalized: dict[str, Any] = {}
    for key in sorted(_NORMALIZED_METADATA_FIELDS & metadata.keys()):
        value = metadata[key]
        if isinstance(value, bool | int | float):
            normalized[key] = value
        elif isinstance(value, str):
            normalized[key] = value[:160]
    return normalized


class FederationService:
    def __init__(
        self,
        session: Session,
        *,
        adapters: AdapterRegistry,
        cipher: EndpointCipher,
        probe_timeout_seconds: float,
        actor_id: str = "system",
        request_id: str | None = None,
    ) -> None:
        self.session = session
        self.repository = FederationRepository(session)
        self.adapters = adapters
        self.cipher = cipher
        self.probe_timeout_seconds = min(max(probe_timeout_seconds, 0.25), 30.0)
        self.actor_id = actor_id
        self.request_id = request_id

    def _audit(self, profile: ConnectionProfile, *, action: str, changes: dict[str, Any]) -> None:
        self.repository.add(
            AuditLog(
                resource_type="connection_profile",
                resource_id=profile.id,
                action=action,
                actor_id=self.actor_id,
                request_id=self.request_id,
                source="api",
                changes=changes,
            )
        )

    def _commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(
                "FEDERATION_CONNECTION_EXISTS",
                "A connection with this camera, name and stream role already exists",
            ) from exc

    def _validate_credential_scope(self, reference: str | None, camera: Camera) -> None:
        if not reference or not reference.startswith("credential-profile:"):
            return
        profile_id = reference.removeprefix("credential-profile:")
        credential = self.session.get(CredentialProfile, profile_id)
        if not credential:
            raise BadRequestError(
                "CREDENTIAL_PROFILE_INVALID",
                "The referenced credential profile does not exist",
            )
        if credential.department_id != camera.department_id:
            raise BadRequestError(
                "CREDENTIAL_PROFILE_SCOPE_MISMATCH",
                "The credential profile belongs to a different department",
            )

    @staticmethod
    def _read(profile: ConnectionProfile) -> ConnectionRead:
        camera = profile.camera
        return ConnectionRead(
            id=profile.id,
            name=profile.name,
            adapter_kind=profile.adapter_kind,
            stream_role=profile.stream_role,
            endpoint_display=profile.endpoint_display,
            endpoint_fingerprint=profile.endpoint_fingerprint,
            enabled=profile.enabled,
            priority=profile.priority,
            verification_status=profile.verification_status,
            last_probe_at=profile.last_probe_at,
            last_probe_latency_ms=profile.last_probe_latency_ms,
            last_error_code=profile.last_error_code,
            last_error_message=profile.last_error_message,
            last_success_at=profile.last_success_at,
            failure_count=profile.failure_count,
            normalized_metadata=profile.normalized_metadata,
            encryption_key_id=profile.encryption_key_id,
            has_credential_reference=bool(profile.credential_reference_ciphertext),
            created_by=profile.created_by,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            camera=ConnectionCameraRead(
                id=camera.id,
                camera_code=camera.camera_code,
                camera_name=camera.camera_name,
                department_id=camera.department_id,
                department_code=camera.department.code,
                department_name=camera.department.name,
                district=camera.district,
                city=camera.city,
                latitude=camera.latitude,
                longitude=camera.longitude,
            ),
        )

    def adapters_list(self) -> AdapterList:
        return AdapterList(
            items=[
                AdapterManifestRead(
                    kind=manifest.kind,
                    label=manifest.label,
                    description=manifest.description,
                    version=manifest.version,
                    schemes=manifest.schemes,
                    capabilities=manifest.capabilities,
                    supports_discovery=manifest.supports_discovery,
                    supports_probe=manifest.supports_probe,
                    supports_stream_handoff=manifest.supports_stream_handoff,
                    available=manifest.available,
                    unavailable_reason=manifest.unavailable_reason,
                )
                for manifest in self.adapters.manifests()
            ]
        )

    def create_connection(self, payload: ConnectionCreate) -> ConnectionRead:
        # Fail before any DNS or filesystem interaction if secrets cannot be
        # protected at rest in this process.
        if not self.cipher.available:
            self.cipher.encrypt("")
        camera = self.repository.get_camera(str(payload.camera_id))
        if not camera:
            raise NotFoundError("camera", str(payload.camera_id))
        if camera.status == "retired":
            raise ConflictError("CAMERA_RETIRED", "Connections cannot be added to a retired camera")
        if self.repository.get_duplicate(
            camera_id=camera.id,
            name=payload.name,
            stream_role=str(payload.stream_role),
        ):
            raise ConflictError(
                "FEDERATION_CONNECTION_EXISTS",
                "A connection with this camera, name and stream role already exists",
            )
        adapter = self.adapters.get(str(payload.adapter_kind))
        endpoint = payload.endpoint.get_secret_value().strip()
        adapter.validate_endpoint(endpoint)
        credential_reference = validate_credential_reference(payload.credential_reference)
        self._validate_credential_scope(credential_reference, camera)
        profile = ConnectionProfile(
            camera_id=camera.id,
            name=payload.name,
            adapter_kind=str(payload.adapter_kind),
            stream_role=str(payload.stream_role),
            endpoint_ciphertext=self.cipher.encrypt(endpoint),
            endpoint_display=adapter.endpoint_display(endpoint),
            endpoint_fingerprint=self.cipher.fingerprint(endpoint),
            credential_reference_ciphertext=(
                self.cipher.encrypt(credential_reference) if credential_reference else None
            ),
            encryption_key_id=self.cipher.key_id,
            enabled=payload.enabled,
            priority=payload.priority,
            verification_status="unverified" if payload.enabled else "disabled",
            created_by=self.actor_id,
        )
        self.repository.add(profile)
        self.session.flush()
        self._audit(
            profile,
            action="connection.created",
            changes={
                "camera_id": camera.id,
                "name": profile.name,
                "adapter_kind": profile.adapter_kind,
                "stream_role": profile.stream_role,
                "endpoint_display": profile.endpoint_display,
                "endpoint_fingerprint": profile.endpoint_fingerprint,
                "has_credential_reference": bool(credential_reference),
                "enabled": profile.enabled,
                "priority": profile.priority,
            },
        )
        self._commit()
        loaded = self.repository.get_connection(profile.id)
        assert loaded is not None
        return self._read(loaded)

    def get_connection(self, connection_id: str) -> ConnectionRead:
        profile = self.repository.get_connection(connection_id)
        if not profile:
            raise NotFoundError("connection_profile", connection_id)
        return self._read(profile)

    def list_connections(
        self, *, filters: ConnectionFilters, page: int, page_size: int
    ) -> ConnectionList:
        items, total = self.repository.list_connections(
            filters=filters, page=page, page_size=page_size
        )
        return ConnectionList(
            items=[self._read(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            pages=page_count(total, page_size),
        )

    def statistics(self, *, filters: ConnectionFilters) -> ConnectionStatistics:
        return ConnectionStatistics(**self.repository.statistics(filters=filters))

    def update_connection(self, connection_id: str, payload: ConnectionUpdate) -> ConnectionRead:
        profile = self.repository.get_connection(connection_id)
        if not profile:
            raise NotFoundError("connection_profile", connection_id)

        requested_name = payload.name if "name" in payload.model_fields_set else profile.name
        requested_role = (
            str(payload.stream_role)
            if "stream_role" in payload.model_fields_set
            else profile.stream_role
        )
        if self.repository.get_duplicate(
            camera_id=profile.camera_id,
            name=requested_name,
            stream_role=requested_role,
            excluding_id=profile.id,
        ):
            raise ConflictError(
                "FEDERATION_CONNECTION_EXISTS",
                "A connection with this camera, name and stream role already exists",
            )

        changes: dict[str, Any] = {}
        endpoint_changed = "endpoint" in payload.model_fields_set
        adapter_changed = "adapter_kind" in payload.model_fields_set
        target_adapter_kind = str(payload.adapter_kind) if adapter_changed else profile.adapter_kind
        if endpoint_changed:
            assert payload.endpoint is not None
            endpoint = payload.endpoint.get_secret_value().strip()
        elif adapter_changed:
            endpoint = self.cipher.decrypt(profile.endpoint_ciphertext)
        else:
            endpoint = None

        if endpoint is not None:
            adapter = self.adapters.get(target_adapter_kind)
            adapter.validate_endpoint(endpoint)
            new_display = adapter.endpoint_display(endpoint)
            new_fingerprint = self.cipher.fingerprint(endpoint)
            changes["endpoint"] = {
                "old_display": profile.endpoint_display,
                "new_display": new_display,
                "old_fingerprint": profile.endpoint_fingerprint,
                "new_fingerprint": new_fingerprint,
            }
            if endpoint_changed:
                profile.endpoint_ciphertext = self.cipher.encrypt(endpoint)
                profile.encryption_key_id = self.cipher.key_id
            profile.endpoint_display = new_display
            profile.endpoint_fingerprint = new_fingerprint
            profile.verification_status = "unverified" if profile.enabled else "disabled"
            profile.last_error_code = None
            profile.last_error_message = None

        for field_name in ("name", "adapter_kind", "stream_role", "priority"):
            if field_name not in payload.model_fields_set:
                continue
            value = getattr(payload, field_name)
            value = str(value) if field_name in {"adapter_kind", "stream_role"} else value
            old_value = getattr(profile, field_name)
            if old_value != value:
                changes[field_name] = {"old": old_value, "new": value}
                setattr(profile, field_name, value)

        if "credential_reference" in payload.model_fields_set:
            new_reference = validate_credential_reference(payload.credential_reference)
            self._validate_credential_scope(new_reference, profile.camera)
            old_present = bool(profile.credential_reference_ciphertext)
            new_present = bool(new_reference)
            if old_present != new_present or new_reference is not None:
                changes["has_credential_reference"] = {
                    "old": old_present,
                    "new": new_present,
                }
                profile.credential_reference_ciphertext = (
                    self.cipher.encrypt(new_reference) if new_reference else None
                )

        if "enabled" in payload.model_fields_set and payload.enabled != profile.enabled:
            changes["enabled"] = {"old": profile.enabled, "new": payload.enabled}
            profile.enabled = bool(payload.enabled)
            profile.verification_status = "unverified" if profile.enabled else "disabled"
            profile.last_error_code = None
            profile.last_error_message = None

        if changes:
            self._audit(profile, action="connection.updated", changes=changes)
        self._commit()
        loaded = self.repository.get_connection(profile.id)
        assert loaded is not None
        return self._read(loaded)

    def probe_connection(self, connection_id: str) -> ConnectionRead:
        profile = self.repository.get_connection(connection_id)
        if not profile:
            raise NotFoundError("connection_profile", connection_id)
        if not profile.enabled:
            raise ConflictError(
                "FEDERATION_CONNECTION_DISABLED",
                "Enable the connection before running a probe",
            )

        endpoint = self.cipher.decrypt(profile.endpoint_ciphertext)
        try:
            adapter = self.adapters.get(profile.adapter_kind)
            result = adapter.probe(endpoint, timeout_seconds=self.probe_timeout_seconds)
        except BadRequestError as exc:
            result = ProbeResult(
                status="blocked",
                latency_ms=0.0,
                error_code=exc.code,
                error_message=exc.message,
            )
        except RegistryError as exc:
            if exc.code != "FEDERATION_ADAPTER_UNAVAILABLE":
                raise
            result = ProbeResult(
                status="adapter_unavailable",
                latency_ms=0.0,
                error_code=exc.code,
                error_message=exc.message,
            )
        except Exception:
            # Adapter/library failures never expose exception text or endpoint
            # material through responses, logs or the audit trail.
            result = ProbeResult(
                status="unreachable",
                latency_ms=0.0,
                error_code="PROBE_FAILED",
                error_message="The adapter could not verify this endpoint",
            )

        observed_at = _utcnow()
        profile.last_probe_at = observed_at
        profile.last_probe_latency_ms = result.latency_ms
        profile.verification_status = result.status
        profile.normalized_metadata = _normalized_metadata(result.metadata)
        profile.last_error_code = result.error_code
        profile.last_error_message = result.error_message
        if result.status == "reachable":
            profile.last_success_at = observed_at
            profile.failure_count = 0
            profile.last_error_code = None
            profile.last_error_message = None
        else:
            profile.failure_count += 1
        self._audit(
            profile,
            action="connection.probed",
            changes={
                "verification_status": result.status,
                "latency_ms": result.latency_ms,
                "error_code": profile.last_error_code,
                "normalized_metadata": profile.normalized_metadata,
                "failure_count": profile.failure_count,
            },
        )
        self._commit()
        loaded = self.repository.get_connection(profile.id)
        assert loaded is not None
        return self._read(loaded)

    def set_enabled(self, connection_id: str, *, enabled: bool) -> ConnectionRead:
        profile = self.repository.get_connection(connection_id)
        if not profile:
            raise NotFoundError("connection_profile", connection_id)
        if profile.enabled != enabled:
            old = profile.enabled
            profile.enabled = enabled
            profile.verification_status = "unverified" if enabled else "disabled"
            profile.last_error_code = None
            profile.last_error_message = None
            self._audit(
                profile,
                action="connection.enabled" if enabled else "connection.disabled",
                changes={"enabled": {"old": old, "new": enabled}},
            )
            self._commit()
        return self._read(profile)

    def connection_audit(
        self, connection_id: str, *, page: int, page_size: int
    ) -> ConnectionAuditList:
        if not self.repository.get_connection(connection_id):
            raise NotFoundError("connection_profile", connection_id)
        items, total = self.repository.list_audit_logs(
            connection_id=connection_id, page=page, page_size=page_size
        )
        return ConnectionAuditList(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=page_count(total, page_size),
        )
