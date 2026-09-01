from __future__ import annotations

import subprocess
from pathlib import Path

from app.media.binary import BinaryResolution
from app.media.hardware import HardwareDecodeCapability, detect_nvdec
from app.media.runtime import MediaRuntimeManager, RuntimeConfig
from app.media.types import RuntimeCameraSummary, RuntimeProfileSummary
from app.stream_engine import DecoderConfig, FFmpegRawDecoder


def test_nvdec_detection_requires_nvidia_cuda_and_decoder_support() -> None:
    def runner(arguments: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output = "cuda\n" if "-hwaccels" in arguments else "V..... h264_cuvid"
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr="")

    capability = detect_nvdec(
        BinaryResolution("ffmpeg", "configured"),
        runner=runner,
        device_probe=lambda _: True,
    )

    assert capability.available is True
    assert capability.backend == "ffmpeg_nvdec"
    assert capability.reason == "nvdec_available"


def test_nvdec_detection_falls_back_when_cuda_is_missing() -> None:
    def runner(arguments: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output = "vaapi\n" if "-hwaccels" in arguments else "V..... h264_cuvid"
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr="")

    capability = detect_nvdec(
        BinaryResolution("ffmpeg", "configured"),
        runner=runner,
        device_probe=lambda _: True,
    )

    assert capability.available is False
    assert capability.backend == "ffmpeg"
    assert capability.reason == "ffmpeg_cuda_unavailable"


def test_nvdec_input_flag_precedes_protected_concat_input() -> None:
    decoder = FFmpegRawDecoder(
        binary=BinaryResolution("ffmpeg", "configured"),
        config=DecoderConfig(width=640, height=360, decode_fps=10),
        source_kind="rtsp",
        hardware_decode=True,
    )

    command = decoder._command()

    assert decoder.backend == "ffmpeg_nvdec"
    assert command[command.index("-hwaccel") + 1] == "cuda"
    assert command.index("-hwaccel") < command.index("-i")


def test_hls_runtime_selects_nvdec_then_allows_per_session_cpu_fallback(
    tmp_path: Path,
) -> None:
    manager = MediaRuntimeManager(
        RuntimeConfig(runtime_root=str(tmp_path / "runtime"), configured_binary="ffmpeg"),
        binary_resolver=lambda _: BinaryResolution("ffmpeg", "configured"),
        hardware_detector=lambda _: HardwareDecodeCapability(
            True, "ffmpeg_nvdec", "nvdec_available"
        ),
    )
    manager.startup()
    session = manager._new_session(
        connection_id="00000000-0000-0000-0000-000000000001",
        endpoint="rtsp://camera/live",
        camera=RuntimeCameraSummary(
            id="00000000-0000-0000-0000-000000000002",
            camera_code="TEST-1",
            camera_name="Test camera",
            department_name="Home",
            district="Ahmedabad",
            city="Ahmedabad",
        ),
        profile=RuntimeProfileSummary(
            id="00000000-0000-0000-0000-000000000003",
            name="Primary",
            adapter_kind="rtsp",
            stream_role="primary",
            endpoint_display="rtsp://c***a/…",
        ),
    )

    gpu_command = manager._build_command(session)
    manager._nvdec_fallback_sessions.add(session.id)
    cpu_command = manager._build_command(session)

    assert gpu_command[gpu_command.index("-hwaccel") + 1] == "cuda"
    assert gpu_command.index("-hwaccel") < gpu_command.index("-i")
    assert "-hwaccel" not in cpu_command
    assert session.decoder_backend == "ffmpeg"
