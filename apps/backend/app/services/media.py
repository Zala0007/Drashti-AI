from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, RegistryError
from app.federation import AdapterRegistry, EndpointCipher
from app.federation.network import NetworkPolicy
from app.media import MediaRuntimeManager
from app.media.credentials import (
    CredentialResolutionUnavailable,
    DatabaseCredentialResolver,
)
from app.media.onvif import OnvifMediaNegotiator
from app.media.runtime import SUPPORTED_RUNTIME_ADAPTERS
from app.media.types import RuntimeCameraSummary, RuntimeProfileSummary
from app.models import AuditLog
from app.repositories import FederationRepository
from app.schemas.media import (
    RuntimeCapabilitiesRead,
    RuntimeSessionList,
    RuntimeSessionRead,
    runtime_session_read,
)


class MediaRuntimeService:
    def __init__(
        self,
        session: Session,
        *,
        manager: MediaRuntimeManager,
        cipher: EndpointCipher,
        adapters: AdapterRegistry,
        media_root: str,
        allowed_cidrs: tuple[str, ...],
        actor_id: str,
        request_id: str | None,
    ) -> None:
        self.session = session
        self.repository = FederationRepository(session)
        self.manager = manager
        self.cipher = cipher
        self.adapters = adapters
        self.media_root = media_root
        self.network_policy = NetworkPolicy(allowed_cidrs)
        self.actor_id = actor_id
        self.request_id = request_id

    def _audit(self, connection_id: str, action: str, changes: dict[str, Any]) -> None:
        self.session.add(
            AuditLog(
                resource_type="connection_profile",
                resource_id=connection_id,
                action=action,
                actor_id=self.actor_id,
                request_id=self.request_id,
                source="runtime",
                changes=changes,
            )
        )
        self.session.commit()

    @staticmethod
    def _summaries(profile: Any) -> tuple[RuntimeCameraSummary, RuntimeProfileSummary]:
        camera = profile.camera
        return (
            RuntimeCameraSummary(
                id=camera.id,
                camera_code=camera.camera_code,
                camera_name=camera.camera_name,
                department_name=camera.department.name,
                district=camera.district,
                city=camera.city,
            ),
            RuntimeProfileSummary(
                id=profile.id,
                name=profile.name,
                adapter_kind=profile.adapter_kind,
                stream_role=profile.stream_role,
                endpoint_display=profile.endpoint_display,
            ),
        )

    def capabilities(self) -> RuntimeCapabilitiesRead:
        return RuntimeCapabilitiesRead(**self.manager.capabilities())

    def list_sessions(self) -> RuntimeSessionList:
        items = [runtime_session_read(item) for item in self.manager.list()]
        return RuntimeSessionList(items=items, total=len(items))

    def get_session(self, session_id: str) -> RuntimeSessionRead:
        return runtime_session_read(self.manager.get(session_id))

    def start(self, connection_id: str) -> RuntimeSessionRead:
        profile = self.repository.get_connection(connection_id)
        if not profile:
            raise NotFoundError("connection_profile", connection_id)
        if not profile.enabled:
            raise ConflictError(
                "FEDERATION_CONNECTION_DISABLED",
                "Enable the connection before starting its media runtime",
            )
        camera_summary, profile_summary = self._summaries(profile)
        if profile.adapter_kind not in SUPPORTED_RUNTIME_ADAPTERS:
            snapshot = self.manager.create_unavailable(
                connection_id=profile.id,
                camera=camera_summary,
                profile=profile_summary,
                error_code="RUNTIME_ADAPTER_UNSUPPORTED",
                error_message=(
                    "This adapter requires a resolved stream URI before runtime handoff"
                ),
            )
            self._audit(
                profile.id,
                "runtime.unavailable",
                {"session_id": snapshot.id, "error_code": snapshot.last_error_code},
            )
            return runtime_session_read(snapshot)

        endpoint = self.cipher.decrypt(profile.endpoint_ciphertext)
        credential_lease = None
        if profile.credential_reference_ciphertext:
            reference = self.cipher.decrypt(profile.credential_reference_ciphertext)
            try:
                credential_lease = DatabaseCredentialResolver(
                    self.session,
                    cipher=self.cipher,
                    department_id=profile.camera.department_id,
                ).resolve(reference)
            except CredentialResolutionUnavailable:
                snapshot = self.manager.create_unavailable(
                    connection_id=profile.id,
                    camera=camera_summary,
                    profile=profile_summary,
                    error_code="RUNTIME_CREDENTIAL_RESOLVER_UNAVAILABLE",
                    error_message=(
                        "A secure credential handoff is not configured for this runtime node"
                    ),
                )
                self._audit(
                    profile.id,
                    "runtime.unavailable",
                    {"session_id": snapshot.id, "error_code": snapshot.last_error_code},
                )
                return runtime_session_read(snapshot)

        try:
            if profile.adapter_kind == "onvif":
                if credential_lease is None:
                    snapshot = self.manager.create_unavailable(
                        connection_id=profile.id,
                        camera=camera_summary,
                        profile=profile_summary,
                        error_code="RUNTIME_ONVIF_CREDENTIAL_REQUIRED",
                        error_message="ONVIF media negotiation requires a credential profile",
                    )
                    self._audit(
                        profile.id,
                        "runtime.unavailable",
                        {"session_id": snapshot.id, "error_code": snapshot.last_error_code},
                    )
                    return runtime_session_read(snapshot)
                try:
                    negotiated = OnvifMediaNegotiator(
                        self.network_policy,
                        timeout_seconds=10.0,
                    ).resolve(
                        endpoint,
                        credentials=credential_lease,
                        stream_role=profile.stream_role,
                    )
                except RegistryError as exc:
                    credential_lease.close()
                    snapshot = self.manager.create_unavailable(
                        connection_id=profile.id,
                        camera=camera_summary,
                        profile=profile_summary,
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                    self._audit(
                        profile.id,
                        "runtime.unavailable",
                        {"session_id": snapshot.id, "error_code": snapshot.last_error_code},
                    )
                    return runtime_session_read(snapshot)
                runtime_endpoint = negotiated.endpoint
                target = self.network_policy.validate_network_endpoint(
                    runtime_endpoint,
                    allowed_schemes=("rtsp",),
                    default_ports={"rtsp": 554},
                )
            else:
                runtime_endpoint = endpoint
                adapter = self.adapters.get(profile.adapter_kind)
                adapter.validate_endpoint(runtime_endpoint)
                target = None
            if profile.adapter_kind in {"rtsp", "onvif"}:
                if target is None:
                    target = self.network_policy.validate_network_endpoint(
                        runtime_endpoint,
                        allowed_schemes=("rtsp",),
                        default_ports={"rtsp": 554},
                    )
                parsed = urlsplit(runtime_endpoint)
                address = target.resolved_ips[0]
                host = f"[{address}]" if ":" in address else address
                runtime_endpoint = urlunsplit(
                    (
                        "rtsp",
                        f"{host}:{target.port}",
                        parsed.path or "/",
                        parsed.query,
                        "",
                    )
                )
            elif profile.adapter_kind == "recorded_file":
                runtime_endpoint = NetworkPolicy.validate_recorded_endpoint(
                    runtime_endpoint, media_root=self.media_root
                ).as_uri()
            if credential_lease:
                runtime_endpoint = credential_lease.authenticated_uri(runtime_endpoint)
        except Exception:
            if credential_lease:
                credential_lease.close()
            raise

        try:
            snapshot = self.manager.start(
                connection_id=profile.id,
                endpoint=runtime_endpoint,
                camera=camera_summary,
                profile=profile_summary,
                credential_lease=credential_lease,
            )
        except Exception:
            if credential_lease:
                credential_lease.close()
            raise
        try:
            if credential_lease and credential_lease.profile_id:
                self.session.add(
                    AuditLog(
                        resource_type="credential_profile",
                        resource_id=credential_lease.profile_id,
                        action="credential.used",
                        actor_id=self.actor_id,
                        request_id=self.request_id,
                        source="runtime",
                        changes={
                            "connection_id": profile.id,
                            "session_id": snapshot.id,
                        },
                    )
                )
            self._audit(
                profile.id,
                "runtime.started",
                {
                    "session_id": snapshot.id,
                    "state": snapshot.state,
                    "adapter_kind": profile.adapter_kind,
                },
            )
        except Exception:
            self.manager.stop(snapshot.id)
            raise
        return runtime_session_read(snapshot)

    def stop(self, session_id: str) -> RuntimeSessionRead:
        snapshot = self.manager.stop(session_id)
        self._audit(
            snapshot.connection_id,
            "runtime.stopped",
            {"session_id": snapshot.id, "state": snapshot.state},
        )
        return runtime_session_read(snapshot)

    def restart(self, session_id: str) -> RuntimeSessionRead:
        snapshot = self.manager.restart(session_id)
        self._audit(
            snapshot.connection_id,
            "runtime.restarted",
            {
                "session_id": snapshot.id,
                "state": snapshot.state,
                "restart_count": snapshot.restart_count,
            },
        )
        return runtime_session_read(snapshot)

    def playlist(self, session_id: str) -> str:
        return self.manager.playlist_text(session_id)

    def segment(self, session_id: str, asset_name: str) -> tuple[Any, int]:
        return self.manager.open_segment(session_id, asset_name)
