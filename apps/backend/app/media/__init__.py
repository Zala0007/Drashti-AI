"""P0.3R supervised media-runtime boundary.

Runtime session state is intentionally process-local for the hackathon PoC.
The public manager contract is isolated so a durable regional scheduler can
replace it without changing federation profiles or HTTP response schemas.
"""

from app.media.binary import BinaryResolution, resolve_ffmpeg_binary
from app.media.credentials import (
    CredentialLease,
    CredentialResolver,
    FailClosedCredentialResolver,
)
from app.media.hardware import HardwareDecodeCapability, detect_nvdec
from app.media.runtime import MediaRuntimeManager, RuntimeConfig
from app.media.types import MediaSessionState, RuntimeSessionSnapshot

__all__ = [
    "BinaryResolution",
    "CredentialLease",
    "CredentialResolver",
    "FailClosedCredentialResolver",
    "HardwareDecodeCapability",
    "MediaRuntimeManager",
    "MediaSessionState",
    "RuntimeConfig",
    "RuntimeSessionSnapshot",
    "detect_nvdec",
    "resolve_ffmpeg_binary",
]
