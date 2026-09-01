from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from app.media.binary import resolve_ffmpeg_binary
from app.stream_engine.engine import StreamEngine, StreamEngineConfig
from app.stream_engine.types import ProcessingCameraSummary, ProcessingProfileSummary


def wait_until_streaming(engine: StreamEngine, camera_ids: list[str], timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        states = {item.camera.id: item.state for item in engine.list()}
        if all(states.get(camera_id) == "streaming" for camera_id in camera_ids):
            return
        time.sleep(0.1)
    raise RuntimeError(f"Streams did not become ready: {states}")


def build_source(path: Path, duration: int) -> None:
    binary = resolve_ffmpeg_binary()
    if binary is None:
        raise RuntimeError("FFmpeg is unavailable")
    subprocess.run(
        [
            binary.path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=10",
            "-t",
            str(duration),
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ],
        check=True,
        timeout=30,
    )


def camera(index: int) -> ProcessingCameraSummary:
    return ProcessingCameraSummary(
        id=f"synthetic-camera-{index:02d}",
        camera_code=f"SYN-CAM-{index:02d}",
        camera_name=f"Synthetic load camera {index:02d}",
        department_id="load-test",
        department_name="P04 Load Test",
        district="Synthetic",
        city="Local",
        latitude=23.0 + index / 10_000,
        longitude=72.0 + index / 10_000,
        vendor="FFmpeg test source",
        model="320x180",
        camera_type="fixed",
    )


def profile(index: int) -> ProcessingProfileSummary:
    return ProcessingProfileSummary(
        id=f"synthetic-profile-{index:02d}",
        name="Synthetic recorded source",
        adapter_kind="recorded_file",
        stream_role="analytics",
        endpoint_display=f"recorded://synthetic-{index:02d}/…",
    )


def run_stage(root: Path, count: int, duration: float) -> dict[str, object]:
    engine = StreamEngine(
        StreamEngineConfig(
            width=320,
            height=180,
            decode_fps=8,
            target_fps=6,
            buffer_size=2,
            max_frame_age_ms=750,
            batch_size=8,
            batch_timeout_ms=30,
            health_timeout_seconds=5,
            freeze_threshold_seconds=5,
            stop_timeout_seconds=1,
            max_active_sessions=count,
        )
    )
    source_template = root / "source-template.mp4"
    source_paths: list[Path] = []
    for index in range(count):
        path = root / f"source-{count:02d}-{index:02d}.mp4"
        shutil.copyfile(source_template, path)
        source_paths.append(path)

    consumer_stop = threading.Event()
    consumed_batches = 0
    consumed_frames = 0

    def consume() -> None:
        nonlocal consumed_batches, consumed_frames
        while not consumer_stop.is_set():
            batch = engine.next_batch(timeout=0.2)
            if batch:
                consumed_batches += 1
                consumed_frames += len(batch.packets)
                time.sleep(0.005)

    engine.startup()
    consumer = threading.Thread(target=consume, name="p04-benchmark-consumer", daemon=True)
    consumer.start()
    camera_ids = [camera(index).id for index in range(count)]
    try:
        for index, source in enumerate(source_paths):
            engine.start(
                camera=camera(index),
                profile=profile(index),
                endpoint=str(source.resolve()),
                source_kind="recorded_file",
            )
        wait_until_streaming(engine, camera_ids)
        time.sleep(1.5)
        engine.metrics()  # Establish the CPU-time baseline after decoder startup.
        samples: list[dict[str, object]] = []
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            time.sleep(1)
            samples.append(engine.metrics())
        sessions = engine.list()

        def numeric(key: str) -> list[float]:
            return [float(sample[key]) for sample in samples]

        return {
            "streams": count,
            "duration_seconds": duration,
            "source": "unique local recorded-file paths (synthetic stress test)",
            "resolution": "320x180",
            "configured_decode_fps": 8,
            "configured_processing_fps": 6,
            "average_decoded_fps_per_stream": round(
                sum(numeric("average_decoded_fps")) / len(samples),
                3,
            ),
            "average_processing_fps_per_stream": round(
                sum(numeric("average_processing_fps")) / len(samples),
                3,
            ),
            "average_frame_age_ms": round(
                sum(numeric("average_latency_ms")) / len(samples),
                3,
            ),
            "average_worker_cpu_percent": round(
                sum(numeric("worker_cpu_percent")) / len(samples),
                3,
            ),
            "peak_worker_memory_mb": round(max(numeric("worker_memory_mb")), 3),
            "gpu": "not available / software decode",
            "network": "not applicable to local-file synthetic test",
            "frames_received": sum(item.metrics.frames_received for item in sessions),
            "frames_dropped": sum(item.metrics.frames_dropped for item in sessions),
            "frames_sampled_out": sum(item.metrics.frames_sampled_out for item in sessions),
            "reconnects": sum(item.metrics.reconnect_count for item in sessions),
            "consumed_batches": consumed_batches,
            "consumed_frames": consumed_frames,
            "all_streams_streaming": all(item.state == "streaming" for item in sessions),
            "per_camera": [
                {
                    "camera": item.camera.camera_code,
                    "decoded_fps": round(item.metrics.decoded_fps, 3),
                    "processing_fps": round(item.metrics.processing_fps, 3),
                    "frame_age_ms": round(item.metrics.current_frame_age_ms or 0, 3),
                    "drops": item.metrics.frames_dropped,
                    "status": item.state,
                }
                for item in sessions
            ],
        }
    finally:
        consumer_stop.set()
        consumer.join(timeout=1)
        engine.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the repeatable P04 synthetic load test")
    parser.add_argument("--counts", nargs="+", type=int, default=[1, 5, 10])
    parser.add_argument("--duration", type=float, default=5)
    arguments = parser.parse_args()
    if not arguments.counts or min(arguments.counts) < 1 or max(arguments.counts) > 50:
        raise SystemExit("Counts must be between 1 and 50")
    with tempfile.TemporaryDirectory(prefix="drishti-p04-load-") as temporary:
        root = Path(temporary)
        build_source(root / "source-template.mp4", max(10, int(arguments.duration) + 5))
        report = {
            "method": (
                "Actual concurrent FFmpeg processes reading unique local files; "
                "P05-compatible consumer drains bounded batches with 5 ms simulated work."
            ),
            "warning": (
                "Synthetic local-file results are not evidence of RTSP network or GPU capacity."
            ),
            "stages": [run_stage(root, count, arguments.duration) for count in arguments.counts],
        }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
