"""Monitoring algorithms adapted from the supplied AI-Features scripts.

Desktop capture, model loading and drawing remain in the standalone scripts.
"""

import math
from collections import deque

import cv2
import numpy as np


class CrossingMonitor:
    """Follow feet across a finite line, with a dead band and confirmation."""

    def __init__(self, line, margin=5, confirmation=2, max_gap=5):
        self.start, self.end = [np.asarray(point, dtype=float) for point in line]
        self.vector = self.end - self.start
        self.length = float(np.linalg.norm(self.vector))
        if not math.isfinite(self.length) or self.length < 1:
            raise ValueError("The boundary needs two distinct, finite endpoints.")
        if margin < 0 or confirmation < 1 or max_gap < 1:
            raise ValueError("Use margin >= 0, confirmation >= 1 and max_gap >= 1.")
        self.margin, self.confirmation, self.max_gap = margin, confirmation, max_gap
        self.people = {}
        self.counts = {"A_TO_B": 0, "B_TO_A": 0}

    def distance(self, point):
        relative = np.asarray(point) - self.start
        return float((self.vector[0] * relative[1] - self.vector[1] * relative[0]) / self.length)

    def side(self, point):
        distance = self.distance(point)
        return 1 if distance > self.margin else -1 if distance < -self.margin else 0

    def intersects(self, previous, current):
        before, after = self.distance(previous), self.distance(current)
        if before * after > 0 or abs(before - after) < 1e-9:
            return False
        fraction = before / (before - after)
        hit = np.asarray(previous) + fraction * (np.asarray(current) - previous)
        along = float(np.dot(hit - self.start, self.vector) / self.length**2)
        return 0 <= along <= 1

    def update(self, person_id, point, frame_number):
        point = np.asarray(point, dtype=float)
        current_side = self.side(point)
        state = self.people.get(person_id)
        if state is None or frame_number - state["last"] > self.max_gap:
            self.people[person_id] = dict(
                side=current_side, previous=point, last=frame_number, crossed=False, count=0
            )
            return None  # Merely appearing on either side is not a crossing.
        if frame_number <= state["last"]:
            raise ValueError("Frame numbers must increase for each person.")
        if frame_number - state["last"] > 1:
            state["count"] = 0
        state["crossed"] |= self.intersects(state["previous"], point)
        state.update(previous=point, last=frame_number)
        if state["side"] == 0:
            state.update(side=current_side, crossed=False, count=0)
        elif current_side == state["side"]:
            state.update(crossed=False, count=0)
        elif current_side == 0:
            state["count"] = 0
        else:
            state["count"] += 1
            if state["count"] >= self.confirmation:
                direction = "A_TO_B" if state["side"] == -1 else "B_TO_A"
                crossed = state["crossed"]
                state.update(side=current_side, crossed=False, count=0)
                if crossed:
                    self.counts[direction] += 1
                    return direction
        return None

    def expire(self, frame_number):
        for person_id in list(self.people):
            if frame_number - self.people[person_id]["last"] > self.max_gap:
                del self.people[person_id]


class EntryMonitor:
    """Confirm entry/exit over consecutive observations to reduce edge jitter."""

    def __init__(self, confirmation=2):
        self.confirmation = confirmation
        self.people = {}

    def update(self, person_id, inside, frame):
        state = self.people.setdefault(person_id, dict(inside=False, count=0, last=frame))
        state["last"] = frame
        if inside == state["inside"]:
            state["count"] = 0
            return False
        state["count"] += 1
        if state["count"] < self.confirmation:
            return False
        state.update(inside=inside, count=0)
        return inside

    def expire(self, frame):
        for person_id in list(self.people):
            gap = frame - self.people[person_id]["last"]
            if gap > 90:
                del self.people[person_id]
            elif gap > 0:
                self.people[person_id]["count"] = 0


class MotionGate:
    """Confirm sustained motion, then emit one alert per motion episode."""

    def __init__(self, confirm_seconds=0.35, clear_seconds=1.0, cooldown=3.0):
        self.confirm_seconds = confirm_seconds
        self.clear_seconds = clear_seconds
        self.cooldown = cooldown
        self.pending_since = None
        self.last_motion = None
        self.last_alert = -math.inf
        self.active = False

    def reset(self):
        self.pending_since = self.last_motion = None
        self.active = False

    def update(self, moving, timestamp):
        if not moving:
            self.pending_since = None
            if self.last_motion is not None and timestamp - self.last_motion >= self.clear_seconds:
                self.active = False
            return False
        self.last_motion = timestamp
        if self.active:
            return False
        if self.pending_since is None:
            self.pending_since = timestamp
        if (
            timestamp - self.pending_since >= self.confirm_seconds
            and timestamp - self.last_alert >= self.cooldown
        ):
            self.active = True
            self.last_alert = timestamp
            return True
        return False


class MotionDetector:
    """Background subtraction with noise filtering and scene-change suppression."""

    def __init__(self, min_area=120, threshold=25, max_foreground=0.55, light_jump=20):
        self.min_area = min_area
        self.threshold = threshold
        self.max_foreground = max_foreground
        self.light_jump = light_jump
        self.background = cv2.createBackgroundSubtractorMOG2(
            history=300,
            varThreshold=threshold,
            detectShadows=True,
        )
        self.previous = None
        self.open_kernel = np.ones((3, 3), np.uint8)
        self.close_kernel = np.ones((5, 5), np.uint8)

    def reset(self):
        self.background = cv2.createBackgroundSubtractorMOG2(
            history=300,
            varThreshold=self.threshold,
            detectShadows=True,
        )
        self.previous = None

    def detect(self, frame):
        # Detection uses denoised original pixels. Brightening is display-only,
        # so the display enhancement does not amplify sensor noise for MOG2.
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        light_change = (
            0.0
            if self.previous is None
            else abs(float(np.median(gray.astype(np.int16) - self.previous.astype(np.int16))))
        )
        self.previous = gray
        foreground = self.background.apply(gray)
        mask = np.where(foreground == 255, 255, 0).astype(np.uint8)  # Exclude MOG2 shadows.
        fraction = float(np.count_nonzero(mask) / mask.size)
        suppressed = fraction > self.max_foreground or light_change > self.light_jump
        if suppressed:
            self.background.apply(gray, learningRate=0.25)
            return [], np.zeros_like(mask), True
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.open_kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.close_kernel)
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
        boxes = []
        for x, y, width, height, area in stats[1:]:
            if area >= self.min_area:
                boxes.append((int(x), int(y), int(x + width), int(y + height)))
        return boxes, mask, False


class MovementPaths:
    """Keep a bounded box-center trail for each currently tracked object."""

    def __init__(self, length=30, max_age=30):
        if length < 2 or max_age < 1:
            raise ValueError("Trail length must be >= 2 and max_age >= 1.")
        self.length, self.max_age = length, max_age
        self.points = {}
        self.last_seen = {}

    def update(self, track_id, box, frame_number):
        # Break the visible path after a missing observation, avoiding a line
        # across an interval where the object's actual movement was not seen.
        if track_id not in self.points or frame_number - self.last_seen[track_id] != 1:
            self.points[track_id] = deque(maxlen=self.length)
        center = (int((box[0] + box[2]) / 2), int((box[1] + box[3]) / 2))
        self.points[track_id].append(center)
        self.last_seen[track_id] = frame_number
        return self.points[track_id]

    def expire(self, frame_number):
        for track_id in list(self.last_seen):
            if frame_number - self.last_seen[track_id] > self.max_age:
                del self.last_seen[track_id]
                del self.points[track_id]
