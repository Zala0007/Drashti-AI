from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from app.errors import BadRequestError

_CLOUD_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
}


@dataclass(frozen=True, slots=True)
class NetworkTarget:
    scheme: str
    hostname: str
    port: int
    resolved_ips: tuple[str, ...]


class NetworkPolicy:
    """Fail-closed endpoint validation for outbound federation probes."""

    def __init__(self, allowed_cidrs: tuple[str, ...] = ()) -> None:
        try:
            self.allowed_networks = tuple(
                ipaddress.ip_network(cidr, strict=False) for cidr in allowed_cidrs
            )
        except ValueError as exc:
            raise ValueError("FEDERATION_ALLOWED_CIDRS contains an invalid CIDR") from exc

    def _explicitly_allowed(self, address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return any(address in network for network in self.allowed_networks)

    def _validate_address(self, raw_address: str) -> None:
        address = ipaddress.ip_address(raw_address)
        if address in _CLOUD_METADATA_IPS:
            raise BadRequestError(
                "FEDERATION_ENDPOINT_BLOCKED",
                "The endpoint resolves to a prohibited metadata service address",
            )
        if address.is_unspecified or address.is_multicast or address.is_link_local:
            raise BadRequestError(
                "FEDERATION_ENDPOINT_BLOCKED",
                "The endpoint resolves to a prohibited network address class",
            )
        # is_reserved includes protocol/documentation ranges. They are never valid
        # operational CCTV targets, even if a broad allowlist was misconfigured.
        if address.is_reserved:
            raise BadRequestError(
                "FEDERATION_ENDPOINT_BLOCKED",
                "The endpoint resolves to a reserved network address",
            )
        if (address.is_private or address.is_loopback) and not self._explicitly_allowed(address):
            raise BadRequestError(
                "FEDERATION_ENDPOINT_BLOCKED",
                "Private and loopback targets require an explicit FEDERATION_ALLOWED_CIDRS entry",
            )
        if not address.is_global and not self._explicitly_allowed(address):
            raise BadRequestError(
                "FEDERATION_ENDPOINT_BLOCKED",
                "Non-public targets require an explicit FEDERATION_ALLOWED_CIDRS entry",
            )

    def validate_network_endpoint(
        self,
        endpoint: str,
        *,
        allowed_schemes: tuple[str, ...],
        default_ports: dict[str, int],
    ) -> NetworkTarget:
        parsed = urlsplit(endpoint)
        scheme = parsed.scheme.lower()
        if scheme not in allowed_schemes:
            raise BadRequestError(
                "FEDERATION_SCHEME_NOT_ALLOWED",
                f"This adapter accepts only: {', '.join(allowed_schemes)}",
            )
        if parsed.username is not None or parsed.password is not None:
            raise BadRequestError(
                "FEDERATION_EMBEDDED_CREDENTIALS",
                "Credentials must not be embedded in connection endpoints",
            )
        credential_query_fragments = {
            "access_key",
            "api_key",
            "apikey",
            "auth",
            "authorization",
            "credential",
            "password",
            "secret",
            "signature",
            "token",
        }
        query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query)}
        if query_keys & credential_query_fragments:
            raise BadRequestError(
                "FEDERATION_EMBEDDED_CREDENTIALS",
                "Credentials must not be embedded in connection endpoint query parameters",
            )
        if not parsed.hostname:
            raise BadRequestError(
                "FEDERATION_ENDPOINT_INVALID", "The connection endpoint must include a hostname"
            )
        try:
            port = parsed.port or default_ports[scheme]
        except ValueError as exc:
            raise BadRequestError(
                "FEDERATION_ENDPOINT_INVALID", "The connection endpoint port is invalid"
            ) from exc
        try:
            records = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise BadRequestError(
                "FEDERATION_DNS_RESOLUTION_FAILED", "The endpoint hostname could not be resolved"
            ) from exc
        resolved = tuple(sorted({record[4][0] for record in records}))
        if not resolved:
            raise BadRequestError(
                "FEDERATION_DNS_RESOLUTION_FAILED", "The endpoint hostname returned no addresses"
            )
        for address in resolved:
            self._validate_address(address)
        return NetworkTarget(scheme, parsed.hostname, port, resolved)

    @staticmethod
    def validate_recorded_endpoint(endpoint: str, *, media_root: str) -> Path:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"file", "recorded"}:
            raise BadRequestError(
                "FEDERATION_SCHEME_NOT_ALLOWED",
                "The recorded-file adapter accepts file:// or recorded:// endpoints",
            )
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise BadRequestError(
                "FEDERATION_ENDPOINT_INVALID",
                "Recorded-file endpoints cannot contain credentials, query strings or fragments",
            )
        root = Path(media_root).expanduser().resolve(strict=False)
        raw_path = unquote(parsed.path)
        if parsed.scheme == "recorded":
            relative = f"{parsed.netloc}{raw_path}".lstrip("/\\")
            candidate = root / relative
        else:
            # file:// paths may be absolute or relative to media root; both are
            # accepted only when the resolved target remains beneath media_root.
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = root / candidate
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise BadRequestError(
                "FEDERATION_FILE_OUTSIDE_MEDIA_ROOT",
                "Recorded media must resolve beneath FEDERATION_MEDIA_ROOT",
            ) from exc
        return resolved
