from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BinaryResolution:
    path: str
    source: str


def _usable_file(candidate: str | None) -> str | None:
    if not candidate:
        return None
    path = Path(candidate).expanduser().resolve(strict=False)
    if path.is_file() and (os.name == "nt" or os.access(path, os.X_OK)):
        return str(path)
    return None


def resolve_ffmpeg_binary(configured: str | None = None) -> BinaryResolution | None:
    """Resolve FFmpeg without downloading binaries at request time."""

    if configured:
        configured_path = _usable_file(configured) or _usable_file(shutil.which(configured))
        if configured_path:
            return BinaryResolution(configured_path, "configured")

    path_binary = _usable_file(shutil.which("ffmpeg"))
    if path_binary:
        return BinaryResolution(path_binary, "path")

    try:
        import imageio_ffmpeg

        fallback = _usable_file(imageio_ffmpeg.get_ffmpeg_exe())
    except (ImportError, OSError, RuntimeError):
        fallback = None
    if fallback:
        return BinaryResolution(fallback, "imageio_ffmpeg")
    return None
