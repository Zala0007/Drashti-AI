from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AdapterManifest:
    kind: str
    label: str
    description: str
    version: str
    schemes: tuple[str, ...]
    capabilities: tuple[str, ...]
    supports_discovery: bool
    supports_probe: bool
    supports_stream_handoff: bool
    available: bool = True
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: str
    latency_ms: float
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class FederationAdapter(Protocol):
    manifest: AdapterManifest

    def validate_endpoint(self, endpoint: str) -> None: ...

    def endpoint_display(self, endpoint: str) -> str: ...

    def probe(self, endpoint: str, *, timeout_seconds: float) -> ProbeResult: ...
