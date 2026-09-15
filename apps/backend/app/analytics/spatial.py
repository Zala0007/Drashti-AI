"""Camera-scoped drawing rules and durable events for live video analytics."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Point(BaseModel):
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)


class SpatialRule(BaseModel):
    feature: Literal["border_line", "virtual_fence", "night_movement", "object_path"]
    enabled: bool = True
    points: list[Point] = Field(default_factory=list, max_length=32)
    direction: Literal["both", "A_TO_B", "B_TO_A"] = "both"

    @model_validator(mode="after")
    def geometry(self):
        if not self.enabled:
            return self
        if self.feature == "border_line":
            if len(self.points) != 2 or self.points[0] == self.points[1]:
                raise ValueError("Draw two distinct border endpoints.")
        elif self.feature in ("virtual_fence", "night_movement"):
            if len(self.points) < 3:
                raise ValueError("Draw at least three polygon corners.")
            area = sum(
                a.x * b.y - b.x * a.y
                for a, b in zip(self.points, self.points[1:] + self.points[:1], strict=True)
            )
            if abs(area) < 0.0001:
                raise ValueError("Draw a polygon with nonzero area.")
        return self


class SpatialAnalytics:
    def __init__(self, database: str):
        self.database = database
        self.lock = threading.RLock()
        self.connection = None
        self.rules = {}
        self.runtime = {}
        self.latest = {}

    def _db(self):
        if self.connection is None:
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.database, check_same_thread=False, timeout=15)
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS spatial_rules (
                  camera TEXT NOT NULL, feature TEXT NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(camera, feature));
                CREATE TABLE IF NOT EXISTS spatial_events (
                  id INTEGER PRIMARY KEY, camera TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS spatial_events_camera ON spatial_events(camera, id);
            """)
            for camera, feature, payload in self.connection.execute("SELECT * FROM spatial_rules"):
                self.rules[(camera, feature)] = SpatialRule.model_validate_json(payload)
        return self.connection

    def save(self, camera: str, rule: SpatialRule):
        with self.lock:
            db = self._db()
            with db:
                if rule.enabled:
                    for key, other in list(self.rules.items()):
                        if key[0] == camera and key[1] != rule.feature and other.enabled:
                            disabled = other.model_copy(update={"enabled": False})
                            db.execute(
                                "UPDATE spatial_rules SET payload=? WHERE camera=? AND feature=?",
                                (disabled.model_dump_json(), *key),
                            )
                            self.rules[key] = disabled
                            self.runtime.pop(key, None)
                db.execute(
                    "INSERT OR REPLACE INTO spatial_rules VALUES (?, ?, ?)",
                    (camera, rule.feature, rule.model_dump_json()),
                )
            self.rules[(camera, rule.feature)] = rule
            self.runtime.pop((camera, rule.feature), None)
            self.latest.pop(camera, None)
            return rule

    def read(self, camera: str):
        with self.lock:
            db = self._db()
            return {
                "rules": [
                    rule.model_dump() for (cam, _), rule in self.rules.items() if cam == camera
                ],
                "events": [
                    dict(json.loads(row[1]), id=row[0])
                    for row in db.execute(
                        "SELECT id, payload FROM spatial_events WHERE camera=? "
                        "ORDER BY id DESC LIMIT 50",
                        (camera,),
                    )
                ],
                "live": self.latest.get(camera),
            }

    def process(self, packet, image, detections):
        with self.lock:
            db = self._db()
            selected = [
                rule
                for (cam, _), rule in self.rules.items()
                if cam == packet.camera_id and rule.enabled
            ]
            if not selected:
                return
            import cv2
            import numpy as np

            from app.analytics.spatial_algorithms import (
                CrossingMonitor,
                EntryMonitor,
                MotionDetector,
                MotionGate,
                MovementPaths,
            )

            width, height = image.size
            timestamp = packet.capture_timestamp.timestamp()
            live = {
                "observed_at": packet.capture_timestamp.isoformat(),
                "paths": [],
                "motion_boxes": [],
                "counts": {},
                "inside": 0,
                "warming_up": False,
            }
            for rule in selected:
                key = (packet.camera_id, rule.feature)
                state = self.runtime.get(key)
                identity = (packet.stream_id, width, height)
                if state is None or state["identity"] != identity:
                    points = [(p.x * width, p.y * height) for p in rule.points]
                    state = {
                        "identity": identity,
                        "tick": 0,
                        "started": timestamp,
                        "points": np.asarray(points, np.float32),
                    }
                    if rule.feature == "border_line":
                        state["monitor"] = CrossingMonitor(points, margin=width * 0.005)
                    elif rule.feature == "virtual_fence":
                        state["monitor"] = EntryMonitor()
                    elif rule.feature == "object_path":
                        state["monitor"] = MovementPaths()
                    else:
                        state["monitor"] = MotionDetector()
                        state["gate"] = MotionGate()
                    self.runtime[key] = state
                state["tick"] += 1
                tick, monitor = state["tick"], state["monitor"]
                events = []
                if rule.feature == "night_movement":
                    frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
                    # Crop to the drawn area's bounding rectangle, then mask outside it.
                    mask = np.zeros((height, width), np.uint8)
                    cv2.fillPoly(mask, [state["points"].astype(np.int32)], 255)
                    frame = cv2.bitwise_and(frame, frame, mask=mask)
                    rx, ry, rw, rh = cv2.boundingRect(state["points"].astype(np.int32))
                    boxes, _, suppressed = monitor.detect(
                        frame[ry : min(ry + rh, height), rx : min(rx + rw, width)]
                    )
                    boxes = [(x1 + rx, y1 + ry, x2 + rx, y2 + ry) for x1, y1, x2, y2 in boxes]
                    live["warming_up"] = timestamp - state["started"] < 2
                    live["motion_boxes"] = [
                        [x1 / width, y1 / height, x2 / width, y2 / height]
                        for x1, y1, x2, y2 in boxes
                    ]
                    if suppressed or live["warming_up"]:
                        state["gate"].reset()
                    elif state["gate"].update(bool(boxes), timestamp):
                        events.append({"event": "night_movement", "track_id": None})
                else:
                    for detection in detections:
                        if detection.kind != "object" or detection.track_id is None:
                            continue
                        track = detection.track_id
                        box = (detection.x1, detection.y1, detection.x2, detection.y2)
                        foot = ((box[0] + box[2]) / 2, box[3])
                        if rule.feature == "object_path":
                            trail = monitor.update(track, box, tick)
                            live["paths"].append(
                                {
                                    "track_id": track,
                                    "class_name": detection.class_name,
                                    "points": [[x / width, y / height] for x, y in trail],
                                }
                            )
                        elif detection.class_name == "person":
                            if rule.feature == "border_line":
                                direction = monitor.update(track, foot, tick)
                                if direction and rule.direction in ("both", direction):
                                    events.append(
                                        {
                                            "event": "boundary_crossed",
                                            "track_id": track,
                                            "direction": direction,
                                        }
                                    )
                            else:
                                inside = cv2.pointPolygonTest(state["points"], foot, False) >= 0
                                live["inside"] += int(inside)
                                if monitor.update(track, inside, tick):
                                    events.append({"event": "person_entered", "track_id": track})
                    monitor.expire(tick)
                    if rule.feature == "border_line":
                        live["counts"] = dict(monitor.counts)
                for event in events:
                    event.update(
                        camera_id=packet.camera_id,
                        feature=rule.feature,
                        observed_at=packet.capture_timestamp.isoformat(),
                        frame=packet.frame_number,
                        stream_id=packet.stream_id,
                    )
                    with db:
                        db.execute(
                            "INSERT INTO spatial_events(camera, payload) VALUES (?, ?)",
                            (packet.camera_id, json.dumps(event)),
                        )
            self.latest[packet.camera_id] = live

    def close(self):
        with self.lock:
            if self.connection is not None:
                self.connection.close()
                self.connection = None
