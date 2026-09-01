from __future__ import annotations

import time
from collections import deque
from threading import Condition

from app.stream_engine.types import FramePacket


class LatestFrameBuffer:
    """Bounded drop-oldest buffer for low-latency live analytics."""

    def __init__(self, capacity: int = 2) -> None:
        if not 1 <= capacity <= 3:
            raise ValueError("Live frame buffer capacity must be between 1 and 3")
        self.capacity = capacity
        self._frames: deque[FramePacket] = deque(maxlen=capacity)
        self._condition = Condition()
        self.frames_written = 0
        self.frames_replaced = 0

    def put(self, frame: FramePacket) -> int:
        with self._condition:
            if len(self._frames) == self.capacity:
                self.frames_replaced += 1
            self._frames.append(frame)
            self.frames_written += 1
            self._condition.notify_all()
            return self.frames_replaced

    def latest(self) -> FramePacket | None:
        with self._condition:
            return self._frames[-1] if self._frames else None

    def latest_after(self, frame_number: int, *, timeout: float) -> FramePacket | None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while True:
                current = self._frames[-1] if self._frames else None
                if current is not None and current.frame_number > frame_number:
                    return current
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def clear(self) -> None:
        with self._condition:
            self._frames.clear()
            self._condition.notify_all()

    @property
    def depth(self) -> int:
        with self._condition:
            return len(self._frames)
