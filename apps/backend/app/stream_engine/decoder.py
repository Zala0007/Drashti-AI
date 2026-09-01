from __future__ import annotations

import math
import os
import queue
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from app.media.binary import BinaryResolution
from app.media.runtime import MediaRuntimeManager, _terminate_process_tree

_URL_PATTERN = re.compile(r"(?i)\b(?:rtsp|https?|file|recorded)://[^\s]+")
_SHOWINFO_PTS_PATTERN = re.compile(
    r"\bn:\s*(?P<frame>\d+)\s+pts:\s*-?\d+\s+pts_time:(?P<seconds>-?[0-9.eE+]+)"
)


class DecoderError(Exception):
    pass


class DecoderEOF(DecoderError):
    pass


@dataclass(frozen=True, slots=True)
class DecodedFrame:
    payload: bytes
    source_pts_seconds: float | None

    def __len__(self) -> int:
        return len(self.payload)


class BinaryProcess(Protocol):
    pid: int
    stdin: BinaryIO | None
    stdout: BinaryIO | None
    stderr: BinaryIO | None

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def send_signal(self, sig: int) -> None: ...


@dataclass(frozen=True, slots=True)
class DecoderConfig:
    width: int
    height: int
    decode_fps: float
    rtsp_transport: str = "tcp"
    read_timeout_seconds: float = 10.0
    stop_timeout_seconds: float = 5.0

    @property
    def frame_bytes(self) -> int:
        return self.width * self.height * 3


def _process_factory(arguments: list[str]) -> BinaryProcess:
    inherited = {
        "DYLD_LIBRARY_PATH",
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
    environment = {key: value for key, value in os.environ.items() if key.upper() in inherited}
    kwargs: dict[str, object] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "bufsize": 0,
        "shell": False,
        "env": environment,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(arguments, **kwargs)  # type: ignore[return-value]


class FFmpegRawDecoder:
    def __init__(
        self,
        *,
        binary: BinaryResolution,
        config: DecoderConfig,
        source_kind: str,
        hardware_decode: bool = False,
        process_factory: Callable[[list[str]], BinaryProcess] = _process_factory,
    ) -> None:
        self.binary = binary
        self.config = config
        self.source_kind = source_kind
        self.hardware_decode = hardware_decode
        self.backend = "ffmpeg_nvdec" if hardware_decode else "ffmpeg"
        self.process_factory = process_factory
        self.process: BinaryProcess | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_tail: list[str] = []
        self._endpoint = ""
        self._pts_queue: queue.Queue[float] = queue.Queue(maxsize=256)

    def _command(self) -> list[str]:
        arguments = [
            self.binary.path,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "info",
        ]
        if self.source_kind in {"rtsp", "onvif"}:
            # FFmpeg's RTSP demuxer still opens the internal ``rtp`` protocol
            # for interleaved RTP-over-TCP media. Network transport remains
            # forced to TCP by ``-rtsp_transport tcp``.
            whitelist = "file,pipe,rtsp,rtp,tcp,udp"
            arguments.extend(
                [
                    "-fflags",
                    "+genpts+discardcorrupt+nobuffer",
                ]
            )
        elif self.source_kind in {"hls", "mjpeg"}:
            whitelist = "file,pipe,http,https,tcp,tls,crypto"
            arguments.extend(
                [
                    "-fflags",
                    "+genpts+discardcorrupt+nobuffer",
                ]
            )
        elif self.source_kind == "recorded_file":
            whitelist = "file,pipe"
            arguments.extend(["-re", "-stream_loop", "-1"])
        else:
            raise DecoderError("The selected adapter cannot provide decoded frames")
        if self.source_kind in {"rtsp", "onvif", "hls", "mjpeg"}:
            # Bound FFmpeg's stream analysis so a valid video track yields its
            # first wall frame promptly instead of waiting on a large probe.
            arguments.extend(
                [
                    "-analyzeduration",
                    "500000",
                    "-probesize",
                    "32768",
                    "-fpsprobesize",
                    "0",
                ]
            )
        if self.hardware_decode:
            # Input-side CUDA acceleration; decoded frames are downloaded for
            # the existing CPU scale and RGB output contract.
            arguments.extend(["-hwaccel", "cuda"])
        video_filter = (
            f"fps={self.config.decode_fps:g},"
            f"scale={self.config.width}:{self.config.height}:force_original_aspect_ratio=decrease,"
            f"pad={self.config.width}:{self.config.height}:(ow-iw)/2:(oh-ih)/2:black,"
            "showinfo"
        )
        arguments.extend(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-protocol_whitelist",
                whitelist,
                "-i",
                "pipe:0",
                "-map",
                "0:v:0",
                "-an",
                "-vf",
                video_filter,
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ]
        )
        return arguments

    def open(self, endpoint: str) -> None:
        if self.process is not None:
            raise DecoderError("Decoder is already open")
        self._endpoint = endpoint
        while not self._pts_queue.empty():
            try:
                self._pts_queue.get_nowait()
            except queue.Empty:
                break
        process = self.process_factory(self._command())
        if process.stdin is None or process.stdout is None:
            _terminate_process_tree(process, timeout_seconds=self.config.stop_timeout_seconds)
            raise DecoderError("Decoder did not expose protected input/output pipes")
        input_options = {
            "timeout": str(int(self.config.read_timeout_seconds * 1_000_000)),
        }
        if self.source_kind in {"rtsp", "onvif"}:
            input_options["rtsp_transport"] = self.config.rtsp_transport
        manifest = MediaRuntimeManager._source_manifest(
            endpoint,
            input_options=input_options,
        ).encode()
        try:
            process.stdin.write(manifest)
            process.stdin.flush()
        finally:
            process.stdin.close()
        self.process = process
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name=f"drishti-decoder-stderr-{process.pid}",
            daemon=True,
        )
        self._stderr_thread.start()

    def _read_stderr(self) -> None:
        process = self.process
        if not process or process.stderr is None:
            return
        while line := process.stderr.readline():
            text = line.decode("utf-8", errors="replace").strip()
            match = _SHOWINFO_PTS_PATTERN.search(text)
            if match:
                try:
                    pts_seconds = float(match.group("seconds"))
                except ValueError:
                    continue
                if math.isfinite(pts_seconds):
                    try:
                        self._pts_queue.put_nowait(pts_seconds)
                    except queue.Full:
                        try:
                            self._pts_queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self._pts_queue.put_nowait(pts_seconds)
                        except queue.Full:
                            pass
                continue
            if self._endpoint:
                text = text.replace(self._endpoint, "[REDACTED_ENDPOINT]")
            text = _URL_PATTERN.sub("[REDACTED_ENDPOINT]", text)[:500]
            self._stderr_tail.append(text)
            if len(self._stderr_tail) > 40:
                del self._stderr_tail[:-40]

    def read_frame(self) -> DecodedFrame:
        process = self.process
        if process is None or process.stdout is None:
            raise DecoderError("Decoder is not open")
        expected = self.config.frame_bytes
        payload = bytearray()
        while len(payload) < expected:
            chunk = process.stdout.read(expected - len(payload))
            if not chunk:
                raise DecoderEOF("The decoder stopped producing frames")
            payload.extend(chunk)
        try:
            pts_seconds = self._pts_queue.get(timeout=1.0)
        except queue.Empty:
            pts_seconds = None
        return DecodedFrame(bytes(payload), pts_seconds)

    def poll(self) -> int | None:
        return self.process.poll() if self.process else None

    def close(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        _terminate_process_tree(process, timeout_seconds=self.config.stop_timeout_seconds)
        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=min(1.0, self.config.stop_timeout_seconds))
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
        self._endpoint = ""

    @property
    def safe_error(self) -> tuple[str, str]:
        tail = "\n".join(self._stderr_tail).casefold()
        if "401" in tail or "403" in tail or "unauthorized" in tail:
            return "STREAM_AUTHENTICATION_FAILED", "The stream rejected the configured identity"
        if "connection refused" in tail:
            return "STREAM_CONNECTION_REFUSED", "The stream refused the decoder connection"
        if "invalid data" in tail or "could not find codec" in tail:
            return "STREAM_DECODE_FAILED", "The stream media could not be decoded"
        return "STREAM_DECODER_EXITED", "The stream decoder exited or stopped producing frames"


class GStreamerDecoder:
    """Optional production backend contract.

    PyGObject/appsink is deliberately not imported unless an edge image provides
    and qualifies it. `auto` currently selects the tested FFmpeg backend.
    """

    backend = "gstreamer"

    @staticmethod
    def available() -> bool:
        try:
            import gi  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return False
        return True
