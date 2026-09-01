from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.errors import ConflictError, RegistryError
from app.federation import AdapterRegistry, EndpointCipher
from app.federation.network import NetworkPolicy
from app.media.credentials import (
    CredentialLease,
    CredentialResolutionUnavailable,
    DatabaseCredentialResolver,
)
from app.media.onvif import OnvifMediaNegotiator
from app.models import ConnectionProfile

DECODABLE_ADAPTERS = {"rtsp", "onvif", "hls", "mjpeg", "recorded_file"}


@dataclass(frozen=True, slots=True)
class ResolvedMediaSource:
    endpoint: str
    source_kind: str
    credential_lease: CredentialLease | None


class MediaSourceResolver:
    """Shared security boundary between P03 connection profiles and media workers."""

    def __init__(
        self,
        session: Session,
        *,
        cipher: EndpointCipher,
        adapters: AdapterRegistry,
        media_root: str,
        allowed_cidrs: tuple[str, ...],
        onvif_timeout_seconds: float = 10.0,
    ) -> None:
        self.session = session
        self.cipher = cipher
        self.adapters = adapters
        self.media_root = media_root
        self.network_policy = NetworkPolicy(allowed_cidrs)
        self.onvif_timeout_seconds = onvif_timeout_seconds

    def resolve(self, profile: ConnectionProfile) -> ResolvedMediaSource:
        if not profile.enabled:
            raise ConflictError(
                "FEDERATION_CONNECTION_DISABLED",
                "Enable the connection before starting stream processing",
            )
        if profile.adapter_kind not in DECODABLE_ADAPTERS:
            raise ConflictError(
                "STREAM_ADAPTER_UNSUPPORTED",
                "This connection must resolve a concrete media URI before P04 handoff",
            )
        endpoint = self.cipher.decrypt(profile.endpoint_ciphertext)
        lease: CredentialLease | None = None
        if profile.credential_reference_ciphertext:
            reference = self.cipher.decrypt(profile.credential_reference_ciphertext)
            try:
                lease = DatabaseCredentialResolver(
                    self.session,
                    cipher=self.cipher,
                    department_id=profile.camera.department_id,
                ).resolve(reference)
            except CredentialResolutionUnavailable as exc:
                raise RegistryError(
                    code="STREAM_CREDENTIAL_RESOLVER_UNAVAILABLE",
                    message="A secure credential handoff is not configured for this stream node",
                    status_code=503,
                ) from exc
        try:
            runtime_endpoint = self._negotiate(profile, endpoint, lease)
            runtime_endpoint = self._validate_and_pin(profile.adapter_kind, runtime_endpoint)
            if lease:
                runtime_endpoint = lease.authenticated_uri(runtime_endpoint)
            return ResolvedMediaSource(runtime_endpoint, profile.adapter_kind, lease)
        except Exception:
            if lease:
                lease.close()
            raise

    def _negotiate(
        self,
        profile: ConnectionProfile,
        endpoint: str,
        lease: CredentialLease | None,
    ) -> str:
        if profile.adapter_kind != "onvif":
            self.adapters.get(profile.adapter_kind).validate_endpoint(endpoint)
            return endpoint
        if lease is None:
            raise ConflictError(
                "STREAM_ONVIF_CREDENTIAL_REQUIRED",
                "ONVIF media negotiation requires a credential profile",
            )
        negotiated = OnvifMediaNegotiator(
            self.network_policy,
            timeout_seconds=self.onvif_timeout_seconds,
        ).resolve(endpoint, credentials=lease, stream_role=profile.stream_role)
        return negotiated.endpoint

    def _validate_and_pin(self, adapter_kind: str, endpoint: str) -> str:
        if adapter_kind in {"rtsp", "onvif"}:
            target = self.network_policy.validate_network_endpoint(
                endpoint,
                allowed_schemes=("rtsp",),
                default_ports={"rtsp": 554},
            )
            parsed = urlsplit(endpoint)
            address = target.resolved_ips[0]
            host = f"[{address}]" if ":" in address else address
            return urlunsplit(
                ("rtsp", f"{host}:{target.port}", parsed.path or "/", parsed.query, "")
            )
        if adapter_kind == "recorded_file":
            path = NetworkPolicy.validate_recorded_endpoint(
                endpoint,
                media_root=self.media_root,
            )
            return str(path)
        # HLS/MJPEG was already policy-validated by its adapter. Edge deployments
        # should prefer a pinned egress proxy for these hostname-based sources.
        return endpoint
