from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.stream_engine.types import (
    FramePacket,
    ProcessingSession,
    ProcessingStreamState,
)


@dataclass(frozen=True, slots=True)
class FrameBatch:
    sequence: int
    created_at: datetime
    packets: tuple[FramePacket, ...]


class FrameScheduler:
    """Fair, latest-frame-first handoff for the next AI module.

    The output queue is intentionally bounded. If P05 cannot keep up, the oldest
    unconsumed batch is replaced and the affected stream metrics record
    backpressure rather than allowing memory and latency to grow.
    """

    def __init__(
        self,
        session_provider: Callable[[], list[ProcessingSession]],
        *,
        batch_size: int,
        batch_timeout_ms: int,
        output_capacity: int = 2,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if batch_timeout_ms < 1:
            raise ValueError("batch_timeout_ms must be positive")
        if output_capacity < 1:
            raise ValueError("output_capacity must be positive")
        self.session_provider = session_provider
        self.batch_size = batch_size
        self.batch_timeout_seconds = batch_timeout_ms / 1000
        self.output_capacity = output_capacity
        self.monotonic = monotonic
        self._condition = threading.Condition()
        self._batches: deque[FrameBatch] = deque(maxlen=output_capacity)
        self._last_frame: dict[str, int] = {}
        self._last_dispatch: dict[str, float] = {}
        self._last_stale: dict[str, int] = {}
        self._sequence = 0
        self._cursor = 0
        self._stop = threading.Event()
        self._consumer_attached = threading.Event()
        self._thread: threading.Thread | None = None

    def startup(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="drishti-frame-scheduler",
            daemon=True,
        )
        self._thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)
        self._thread = None

    def _ordered_sessions(self) -> list[ProcessingSession]:
        sessions = self.session_provider()
        if not sessions:
            return []
        sessions.sort(key=lambda item: item.id)
        offset = self._cursor % len(sessions)
        self._cursor = (offset + self.batch_size) % len(sessions)
        return sessions[offset:] + sessions[:offset]

    def _candidate(
        self,
        session: ProcessingSession,
        now: datetime,
        tick: float,
    ) -> FramePacket | None:
        with session.lock:
            if session.state not in {
                ProcessingStreamState.streaming,
                ProcessingStreamState.degraded,
            }:
                return None
            packet = session.buffer.latest() if session.buffer is not None else None
            if packet is None or self._last_frame.get(session.id, -1) >= packet.frame_number:
                return None
            minimum_interval = 1 / session.target_fps
            if tick - self._last_dispatch.get(session.id, 0.0) < minimum_interval:
                return None
            age_ms = packet.age_ms(now)
            session.metrics.current_frame_age_ms = age_ms
            session.metrics.latency_estimate_ms = age_ms
            if age_ms > session.max_frame_age_ms:
                if self._last_stale.get(session.id) != packet.frame_number:
                    session.metrics.stale_frames_dropped += 1
                    session.metrics.frames_dropped += 1
                    self._last_stale[session.id] = packet.frame_number
                self._last_frame[session.id] = packet.frame_number
                return None
            previous = self._last_frame.get(session.id)
            if previous is not None and packet.frame_number > previous + 1:
                sampled = packet.frame_number - previous - 1
                session.metrics.frames_sampled_out += sampled
                session.metrics.frames_dropped += sampled
            return packet

    def _record_dispatch(
        self,
        session: ProcessingSession,
        packet: FramePacket,
        now: datetime,
        tick: float,
    ) -> None:
        age_ms = packet.age_ms(now)
        with session.lock:
            self._last_frame[session.id] = packet.frame_number
            self._last_dispatch[session.id] = tick
            session.metrics.frames_dispatched += 1
            session.metrics.last_dispatch_at = now
            samples = session.age_samples_ms
            samples.append(age_ms)
            if len(samples) > 256:
                del samples[:-256]
            ordered = sorted(samples)
            p95_index = min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))
            session.metrics.current_frame_age_ms = age_ms
            session.metrics.average_frame_age_ms = sum(samples) / len(samples)
            session.metrics.p95_frame_age_ms = ordered[p95_index]
            session.metrics.max_frame_age_ms = max(samples)
            if session.dispatch_window_started is None:
                session.dispatch_window_started = tick
                session.dispatch_window_frames = 1
            else:
                session.dispatch_window_frames += 1
                elapsed = tick - session.dispatch_window_started
                if elapsed >= 1.0:
                    session.metrics.processing_fps = session.dispatch_window_frames / elapsed
                    session.dispatch_window_started = tick
                    session.dispatch_window_frames = 0

    def _publish(self, packets: list[tuple[ProcessingSession, FramePacket]]) -> None:
        if not packets:
            return
        now = datetime.now(UTC)
        tick = self.monotonic()
        self._sequence += 1
        batch = FrameBatch(
            sequence=self._sequence,
            created_at=now,
            packets=tuple(packet for _, packet in packets),
        )
        with self._condition:
            if len(self._batches) == self.output_capacity:
                dropped = self._batches.popleft()
                affected = {packet.stream_id for packet in dropped.packets}
                for session in self.session_provider():
                    if session.id in affected:
                        with session.lock:
                            session.metrics.dropped_due_to_backpressure += 1
                            session.metrics.frames_dropped += 1
            self._batches.append(batch)
            self._condition.notify_all()
        for session, packet in packets:
            self._record_dispatch(session, packet, now, tick)

    def _run(self) -> None:
        while not self._stop.wait(self.batch_timeout_seconds):
            if not self._consumer_attached.is_set():
                continue
            now = datetime.now(UTC)
            tick = self.monotonic()
            selected: list[tuple[ProcessingSession, FramePacket]] = []
            for session in self._ordered_sessions():
                packet = self._candidate(session, now, tick)
                if packet is not None:
                    selected.append((session, packet))
                if len(selected) >= self.batch_size:
                    break
            self._publish(selected)

    def next_batch(self, timeout: float | None = None) -> FrameBatch | None:
        self._consumer_attached.set()
        deadline = None if timeout is None else self.monotonic() + max(0.0, timeout)
        with self._condition:
            while not self._batches and not self._stop.is_set():
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - self.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._batches.popleft() if self._batches else None

    @property
    def queue_depth(self) -> int:
        with self._condition:
            return len(self._batches)

    @property
    def consumer_attached(self) -> bool:
        return self._consumer_attached.is_set()

    def forget(self, stream_id: str) -> None:
        self._last_frame.pop(stream_id, None)
        self._last_dispatch.pop(stream_id, None)
        self._last_stale.pop(stream_id, None)
        with self._condition:
            retained: deque[FrameBatch] = deque(maxlen=self.output_capacity)
            for batch in self._batches:
                packets = tuple(packet for packet in batch.packets if packet.stream_id != stream_id)
                if packets:
                    retained.append(
                        FrameBatch(
                            sequence=batch.sequence,
                            created_at=batch.created_at,
                            packets=packets,
                        )
                    )
            self._batches = retained
            self._condition.notify_all()
