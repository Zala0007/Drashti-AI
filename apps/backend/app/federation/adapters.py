from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from pathlib import Path
from urllib.parse import urlsplit

from app.errors import BadRequestError, RegistryError
from app.federation.network import NetworkPolicy, NetworkTarget
from app.federation.types import AdapterManifest, FederationAdapter, ProbeResult

_SAFE_FAILURE_MESSAGES = {
    "PROBE_TIMEOUT": "The endpoint did not respond before the probe timeout",
    "CONNECTION_REFUSED": "The endpoint refused the probe connection",
    "NETWORK_UNREACHABLE": "The endpoint could not be reached",
    "TLS_ERROR": "A secure connection could not be established",
    "HTTP_ERROR": "The endpoint returned an unsuccessful response",
    "CONTENT_TYPE_MISMATCH": "The endpoint response is not compatible with this adapter",
    "CONTENT_SIGNATURE_MISMATCH": "The endpoint payload is not compatible with this adapter",
    "EMPTY_RECORDED_FILE": "The recorded media file is empty",
    "RECORDED_FILE_NOT_FOUND": "The recorded media file was not found",
    "PROBE_FAILED": "The adapter could not verify this endpoint",
    "PROTOCOL_ERROR": "The endpoint returned a malformed protocol response",
}


def _failure(*, started: float, code: str, status: str = "unreachable") -> ProbeResult:
    return ProbeResult(
        status=status,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
        error_code=code,
        error_message=_SAFE_FAILURE_MESSAGES[code],
    )


def _network_failure(started: float, exc: Exception) -> ProbeResult:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return _failure(started=started, code="PROBE_TIMEOUT")
    if isinstance(exc, ssl.SSLError):
        return _failure(started=started, code="TLS_ERROR")
    if isinstance(exc, ConnectionRefusedError):
        return _failure(started=started, code="CONNECTION_REFUSED")
    if isinstance(exc, http.client.HTTPException):
        return _failure(started=started, code="PROTOCOL_ERROR", status="misconfigured")
    return _failure(started=started, code="NETWORK_UNREACHABLE")


def _authority_display(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    raw_hostname = parsed.hostname or "endpoint"
    try:
        address = ipaddress.ip_address(raw_hostname)
    except ValueError:
        labels = raw_hostname.split(".")
        masked_labels = [
            "*" if len(label) <= 2 else f"{label[0]}***{label[-1]}" for label in labels
        ]
        hostname = ".".join(masked_labels)
    else:
        if address.version == 4:
            octets = raw_hostname.split(".")
            hostname = f"{octets[0]}.{octets[1]}.x.x"
        else:
            hostname = ":".join(address.exploded.split(":")[:2]) + "::…"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme.lower()}://{hostname}{port}/…"


class _NetworkAdapter:
    default_ports: dict[str, int]

    def __init__(self, policy: NetworkPolicy) -> None:
        self.policy = policy

    def _target(self, endpoint: str) -> NetworkTarget:
        return self.policy.validate_network_endpoint(
            endpoint,
            allowed_schemes=self.manifest.schemes,
            default_ports=self.default_ports,
        )

    def validate_endpoint(self, endpoint: str) -> None:
        self._target(endpoint)

    def endpoint_display(self, endpoint: str) -> str:
        return _authority_display(endpoint)


class RtspAdapter(_NetworkAdapter):
    manifest = AdapterManifest(
        kind="rtsp",
        label="RTSP Stream",
        description=("RTSP OPTIONS reachability and downstream handoff without media decoding."),
        version="1.0",
        schemes=("rtsp",),
        capabilities=("reachability_probe", "rtsp_options", "stream_handoff"),
        supports_discovery=False,
        supports_probe=True,
        supports_stream_handoff=True,
    )
    default_ports = {"rtsp": 554}

    def probe(self, endpoint: str, *, timeout_seconds: float) -> ProbeResult:
        started = time.perf_counter()
        target = self._target(endpoint)
        try:
            with socket.create_connection(
                (target.resolved_ips[0], target.port), timeout=timeout_seconds
            ) as connection:
                connection.settimeout(timeout_seconds)
                request = (
                    f"OPTIONS {endpoint} RTSP/1.0\r\n"
                    "CSeq: 1\r\n"
                    "User-Agent: Drishti-AI-Federation/1.0\r\n\r\n"
                )
                connection.sendall(request.encode("utf-8"))
                response = connection.recv(4096).decode("iso-8859-1", errors="replace")
        except OSError as exc:
            return _network_failure(started, exc)
        first_line = response.splitlines()[0] if response else ""
        parts = first_line.split(" ", 2)
        try:
            status_code = int(parts[1])
        except (IndexError, ValueError):
            return _failure(started=started, code="PROBE_FAILED", status="misconfigured")
        latency = round((time.perf_counter() - started) * 1000, 3)
        if status_code in {401, 403}:
            return ProbeResult(
                "authentication_required",
                latency,
                "AUTHENTICATION_REQUIRED",
                "The endpoint requires credentials",
                {"protocol": "rtsp", "status_code": status_code},
            )
        if 200 <= status_code < 400:
            return ProbeResult(
                "reachable", latency, metadata={"protocol": "rtsp", "status_code": status_code}
            )
        return ProbeResult(
            "misconfigured",
            latency,
            "RTSP_STATUS_ERROR",
            "The RTSP endpoint returned an unsuccessful response",
            {"protocol": "rtsp", "status_code": status_code},
        )


class _HttpAdapter(_NetworkAdapter):
    default_ports = {"http": 80, "https": 443}
    expected_content_types: tuple[str, ...] = ()
    accept = "*/*"

    def _request_components(self) -> tuple[str, dict[str, str], bytes | None, int]:
        return (
            "GET",
            {"Accept": self.accept, "User-Agent": "Drishti-AI-Federation/1.0"},
            None,
            0,
        )

    def _validate_prefix(self, prefix: bytes) -> bool:
        del prefix
        return True

    @staticmethod
    def _pinned_request(
        endpoint: str,
        *,
        target: NetworkTarget,
        timeout_seconds: float,
        method: str,
        headers: dict[str, str],
        body: bytes | None,
        response_prefix_limit: int,
    ) -> tuple[int, str, bytes]:
        """Connect to a policy-approved IP while preserving HTTP Host and TLS SNI.

        This closes the validation/use DNS-rebinding gap: the hostname is never
        resolved by the HTTP client after NetworkPolicy approval.
        """

        parsed = urlsplit(endpoint)
        request_target = parsed.path or "/"
        if parsed.query:
            request_target = f"{request_target}?{parsed.query}"
        deadline = time.monotonic() + timeout_seconds
        last_error: OSError | ssl.SSLError | http.client.HTTPException | None = None

        def remaining_timeout() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("federation probe deadline exceeded")
            return remaining

        for resolved_ip in target.resolved_ips:
            connection = http.client.HTTPConnection(
                target.hostname, target.port, timeout=remaining_timeout()
            )
            try:
                raw_socket = socket.create_connection(
                    (resolved_ip, target.port), timeout=remaining_timeout()
                )
                if target.scheme == "https":
                    context = ssl.create_default_context()
                    raw_socket.settimeout(remaining_timeout())
                    raw_socket = context.wrap_socket(raw_socket, server_hostname=target.hostname)
                connection.sock = raw_socket
                connection.sock.settimeout(remaining_timeout())
                connection.request(method, request_target, body=body, headers=headers)
                connection.sock.settimeout(remaining_timeout())
                response = connection.getresponse()
                content_type = response.getheader("Content-Type", "").split(";", 1)[0].lower()
                status_code = response.status
                connection.sock.settimeout(remaining_timeout())
                prefix = response.read(response_prefix_limit) if response_prefix_limit > 0 else b""
                response.close()
                return status_code, content_type, prefix
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                last_error = exc
            finally:
                connection.close()
        assert last_error is not None
        raise last_error

    def probe(self, endpoint: str, *, timeout_seconds: float) -> ProbeResult:
        started = time.perf_counter()
        target = self._target(endpoint)
        method, headers, body, response_prefix_limit = self._request_components()
        try:
            status_code, content_type, prefix = self._pinned_request(
                endpoint,
                target=target,
                timeout_seconds=timeout_seconds,
                method=method,
                headers=headers,
                body=body,
                response_prefix_limit=response_prefix_limit,
            )
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            return _network_failure(started, exc)
        latency = round((time.perf_counter() - started) * 1000, 3)
        metadata = {"protocol": "http", "status_code": status_code}
        if content_type:
            metadata["content_type"] = content_type
        if status_code in {401, 403}:
            return ProbeResult(
                "authentication_required",
                latency,
                "AUTHENTICATION_REQUIRED",
                "The endpoint requires credentials",
                metadata,
            )
        if not 200 <= status_code < 400:
            return ProbeResult(
                "misconfigured",
                latency,
                "HTTP_STATUS_ERROR",
                _SAFE_FAILURE_MESSAGES["HTTP_ERROR"],
                metadata,
            )
        if self.expected_content_types and not any(
            expected in content_type for expected in self.expected_content_types
        ):
            return ProbeResult(
                "misconfigured",
                latency,
                "CONTENT_TYPE_MISMATCH",
                _SAFE_FAILURE_MESSAGES["CONTENT_TYPE_MISMATCH"],
                metadata,
            )
        if not self._validate_prefix(prefix):
            return ProbeResult(
                "misconfigured",
                latency,
                "CONTENT_SIGNATURE_MISMATCH",
                _SAFE_FAILURE_MESSAGES["CONTENT_SIGNATURE_MISMATCH"],
                metadata,
            )
        return ProbeResult("reachable", latency, metadata=metadata)


class HlsAdapter(_HttpAdapter):
    manifest = AdapterManifest(
        kind="hls",
        label="HLS Playlist",
        description=(
            "HTTP playlist verification using a bounded #EXTM3U prefix; segments are not fetched."
        ),
        version="1.0",
        schemes=("http", "https"),
        capabilities=("reachability_probe", "playlist_validation", "stream_handoff"),
        supports_discovery=False,
        supports_probe=True,
        supports_stream_handoff=True,
    )
    expected_content_types = (
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
        "audio/mpegurl",
    )
    accept = "application/vnd.apple.mpegurl, application/x-mpegurl"

    def _request_components(self) -> tuple[str, dict[str, str], bytes | None, int]:
        method, headers, body, _ = super()._request_components()
        return method, headers, body, 4096

    def _validate_prefix(self, prefix: bytes) -> bool:
        text = prefix.decode("utf-8", errors="replace").lstrip("\ufeff \t\r\n")
        return text.startswith("#EXTM3U")


class MjpegAdapter(_HttpAdapter):
    manifest = AdapterManifest(
        kind="mjpeg",
        label="MJPEG Stream",
        description=(
            "HTTP status and content-type verification without buffering the continuous body."
        ),
        version="1.0",
        schemes=("http", "https"),
        capabilities=("reachability_probe", "content_type_validation", "stream_handoff"),
        supports_discovery=False,
        supports_probe=True,
        supports_stream_handoff=True,
    )
    expected_content_types = ("multipart/x-mixed-replace", "image/jpeg")
    accept = "multipart/x-mixed-replace, image/jpeg"


class VmsHttpAdapter(_HttpAdapter):
    manifest = AdapterManifest(
        kind="vms_http",
        label="Generic VMS HTTP API",
        description=(
            "Vendor-neutral HTTP reachability; vendor SDK behavior belongs in a dedicated plugin."
        ),
        version="1.0",
        schemes=("http", "https"),
        capabilities=("reachability_probe", "http_api_handoff"),
        supports_discovery=False,
        supports_probe=True,
        supports_stream_handoff=False,
    )


class OnvifAdapter(_HttpAdapter):
    manifest = AdapterManifest(
        kind="onvif",
        label="ONVIF Device Service",
        description=(
            "SOAP device-service reachability with authenticated Media1 profile negotiation."
        ),
        version="1.1",
        schemes=("http", "https"),
        capabilities=(
            "soap_reachability_probe",
            "device_service_handoff",
            "media_profile_negotiation",
            "stream_handoff",
        ),
        supports_discovery=False,
        supports_probe=True,
        supports_stream_handoff=True,
    )

    def _request_components(self) -> tuple[str, dict[str, str], bytes | None, int]:
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
            '<s:Body><GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>'
            "</s:Body></s:Envelope>"
        )
        return (
            "POST",
            {
                "Content-Type": "application/soap+xml; charset=utf-8",
                "User-Agent": "Drishti-AI-Federation/1.0",
            },
            envelope.encode("utf-8"),
            0,
        )


class RecordedFileAdapter:
    manifest = AdapterManifest(
        kind="recorded_file",
        label="Recorded Media File",
        description=(
            "File presence and size verification inside the approved media root without decoding."
        ),
        version="1.0",
        schemes=("file", "recorded"),
        capabilities=("file_presence_probe", "recorded_media_handoff"),
        supports_discovery=False,
        supports_probe=True,
        supports_stream_handoff=True,
    )

    def __init__(self, *, media_root: str) -> None:
        self.media_root = media_root

    def _path(self, endpoint: str) -> Path:
        return NetworkPolicy.validate_recorded_endpoint(endpoint, media_root=self.media_root)

    def validate_endpoint(self, endpoint: str) -> None:
        self._path(endpoint)

    def endpoint_display(self, endpoint: str) -> str:
        path = self._path(endpoint)
        suffix = path.suffix.lower()[:16]
        return f"recorded://…/…{suffix}"

    def probe(self, endpoint: str, *, timeout_seconds: float) -> ProbeResult:
        del timeout_seconds
        started = time.perf_counter()
        path = self._path(endpoint)
        try:
            stat = path.stat()
        except (FileNotFoundError, NotADirectoryError):
            return _failure(started=started, code="RECORDED_FILE_NOT_FOUND")
        except OSError:
            return _failure(started=started, code="PROBE_FAILED")
        if not path.is_file():
            return _failure(started=started, code="RECORDED_FILE_NOT_FOUND")
        if stat.st_size <= 0:
            return _failure(started=started, code="EMPTY_RECORDED_FILE", status="misconfigured")
        return ProbeResult(
            "reachable",
            round((time.perf_counter() - started) * 1000, 3),
            metadata={"media_type": "recorded_file", "size_bytes": stat.st_size},
        )


class AdapterRegistry:
    def __init__(self, adapters: list[FederationAdapter]) -> None:
        self._adapters = {adapter.manifest.kind: adapter for adapter in adapters}

    def manifests(self) -> list[AdapterManifest]:
        return [self._adapters[kind].manifest for kind in sorted(self._adapters)]

    def get(self, kind: str) -> FederationAdapter:
        adapter = self._adapters.get(kind)
        if not adapter:
            raise BadRequestError(
                "FEDERATION_ADAPTER_UNKNOWN", "The requested federation adapter is not registered"
            )
        if not adapter.manifest.available:
            raise RegistryError(
                code="FEDERATION_ADAPTER_UNAVAILABLE",
                message="The requested federation adapter is currently unavailable",
                status_code=503,
            )
        return adapter


def build_adapter_registry(*, allowed_cidrs: tuple[str, ...], media_root: str) -> AdapterRegistry:
    policy = NetworkPolicy(allowed_cidrs)
    return AdapterRegistry(
        [
            RtspAdapter(policy),
            HlsAdapter(policy),
            MjpegAdapter(policy),
            OnvifAdapter(policy),
            VmsHttpAdapter(policy),
            RecordedFileAdapter(media_root=media_root),
        ]
    )
