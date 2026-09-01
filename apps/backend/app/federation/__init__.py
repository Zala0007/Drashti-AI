"""Vendor-neutral stream federation boundary.

P0.3 verifies reachability and produces safe handoff metadata. Media decoding,
recording, transcoding and AI inference intentionally remain outside this
package and are introduced by later pipeline modules.
"""

from app.federation.adapters import AdapterRegistry, build_adapter_registry
from app.federation.network import NetworkPolicy
from app.federation.security import EndpointCipher
from app.federation.types import AdapterManifest, ProbeResult

__all__ = [
    "AdapterManifest",
    "AdapterRegistry",
    "EndpointCipher",
    "NetworkPolicy",
    "ProbeResult",
    "build_adapter_registry",
]
