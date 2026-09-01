from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.media.binary import BinaryResolution


@dataclass(frozen=True, slots=True)
class HardwareDecodeCapability:
    available: bool
    backend: str
    reason: str


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _probe_environment() -> dict[str, str]:
    inherited = {
        "HOME",
        "LANG",
        "LC_ALL",
        "LD_LIBRARY_PATH",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in inherited}


def _run_probe(runner: CommandRunner, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return runner(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
        check=False,
        shell=False,
        env=_probe_environment(),
    )


def _nvidia_device_visible(runner: CommandRunner) -> bool:
    if os.name != "nt" and any(
        Path(candidate).exists() for candidate in ("/dev/nvidia0", "/dev/nvidiactl")
    ):
        return True
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi and os.name == "nt":
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        candidate = Path(system_root) / "System32" / "nvidia-smi.exe"
        nvidia_smi = str(candidate) if candidate.is_file() else None
    if not nvidia_smi:
        return False
    try:
        result = _run_probe(
            runner,
            [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def detect_nvdec(
    binary: BinaryResolution | None,
    *,
    runner: CommandRunner = subprocess.run,
    device_probe: Callable[[CommandRunner], bool] = _nvidia_device_visible,
) -> HardwareDecodeCapability:
    """Detect a usable NVIDIA decode path without downloading or loading media."""

    if binary is None:
        return HardwareDecodeCapability(False, "ffmpeg", "ffmpeg_unavailable")
    if not device_probe(runner):
        return HardwareDecodeCapability(False, "ffmpeg", "nvidia_device_unavailable")
    try:
        accelerators = _run_probe(runner, [binary.path, "-hide_banner", "-hwaccels"])
        decoders = _run_probe(runner, [binary.path, "-hide_banner", "-decoders"])
    except (OSError, subprocess.SubprocessError):
        return HardwareDecodeCapability(False, "ffmpeg", "ffmpeg_capability_probe_failed")
    accelerator_output = f"{accelerators.stdout}\n{accelerators.stderr}".casefold()
    decoder_output = f"{decoders.stdout}\n{decoders.stderr}".casefold()
    if accelerators.returncode != 0 or "cuda" not in accelerator_output.split():
        return HardwareDecodeCapability(False, "ffmpeg", "ffmpeg_cuda_unavailable")
    if decoders.returncode != 0 or not any(
        marker in decoder_output for marker in ("_cuvid", "_nvdec")
    ):
        return HardwareDecodeCapability(False, "ffmpeg", "ffmpeg_nvdec_decoder_unavailable")
    return HardwareDecodeCapability(True, "ffmpeg_nvdec", "nvdec_available")
