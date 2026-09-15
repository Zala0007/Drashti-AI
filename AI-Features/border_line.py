"""Standalone SAHI + YOLO26 app for directional border-line crossing alerts."""

import argparse
import json
import math
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

WINDOW = "Border Line Crossing"


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
            self.people[person_id] = dict(side=current_side, previous=point, last=frame_number,
                                          crossed=False, count=0)
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


class PersonDetector:
    """Standalone detection and tracking; does not import the virtual fence app."""

    def __init__(self, args):
        from ultralytics import YOLO
        from ultralytics.trackers.byte_tracker import BYTETracker

        self.args = args
        # Relative paths avoid Ultralytics stripping the workspace's apostrophe.
        model_path = os.path.relpath(args.model) if Path(args.model).is_file() else args.model
        self.model = YOLO(model_path)
        self.sahi_model = None
        if args.sahi:
            from sahi import AutoDetectionModel

            device = f"cuda:{args.device}" if args.device and args.device.isdecimal() else args.device
            self.sahi_model = AutoDetectionModel.from_pretrained(
                model_type="ultralytics", model=self.model, device=device,
                confidence_threshold=args.conf, image_size=args.imgsz,
            )
            self.model.overrides["classes"] = [0]
        self.tracker = BYTETracker(SimpleNamespace(
            track_high_thresh=args.conf, track_low_thresh=min(0.1, args.conf),
            new_track_thresh=args.conf, track_buffer=30, match_thresh=0.8, fuse_score=False,
        ))

    def predict(self, frame):
        from ultralytics.engine.results import Boxes

        if self.sahi_model is not None:
            from sahi.predict import get_sliced_prediction

            prediction = get_sliced_prediction(
                cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), self.sahi_model,
                slice_height=self.args.slice_size, slice_width=self.args.slice_size,
                overlap_height_ratio=0.2, overlap_width_ratio=0.2, verbose=0,
            )
            rows = [[*item.bbox.to_xyxy(), item.score.value, 0]
                    for item in prediction.object_prediction_list if item.category.id == 0]
            boxes = Boxes(np.asarray(rows, np.float32).reshape(-1, 6), frame.shape[:2])
        else:
            boxes = self.model.predict(frame, classes=[0], conf=self.args.conf,
                                       imgsz=self.args.imgsz, device=self.args.device,
                                       verbose=False)[0].boxes.cpu().numpy()
        return self.tracker.update(boxes, frame)


def paint_line(frame, line):
    start, end = np.asarray(line, np.int32)
    cv2.arrowedLine(frame, tuple(start), tuple(end), (0, 220, 255), 2, tipLength=0.06)
    vector = end - start
    length = np.linalg.norm(vector)
    if length < 1:
        return
    midpoint = (start + end) / 2
    normal = np.array([-vector[1], vector[0]]) / length
    height, width = frame.shape[:2]
    for label, sign in (("A", -1), ("B", 1)):
        point = midpoint + sign * normal * 35
        position = (int(np.clip(point[0], 5, width - 20)), int(np.clip(point[1], 75, height - 8)))
        cv2.putText(frame, label, position, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 220, 255), 2)


def draw_line(frame, path):
    points = []

    def mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 2:
            points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()

    cv2.setMouseCallback(WINDOW, mouse)
    try:
        while True:
            display = frame.copy()
            for point in points:
                cv2.circle(display, point, 5, (0, 220, 255), -1)
            if len(points) == 2:
                paint_line(display, points)
            cv2.putText(display, "Click 2 endpoints | Enter start | Right-click undo | R reset | Q quit",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
            cv2.imshow(WINDOW, display)
            key = cv2.waitKey(20) & 0xFF
            if key in (13, 10) and len(points) == 2:
                if np.linalg.norm(np.subtract(points[1], points[0])) < 20:
                    print("Draw a line at least 20 pixels long.")
                    continue
                height, width = frame.shape[:2]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps([[x / width, y / height] for x, y in points]), encoding="utf-8")
                return np.asarray(points, np.int32)
            if key == ord("r"):
                points.clear()
            if key in (27, ord("q")) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                return None
    finally:
        cv2.setMouseCallback(WINDOW, lambda *args: None)


def load_line(path, frame):
    points = np.asarray(json.loads(path.read_text(encoding="utf-8")), dtype=float)
    if points.shape != (2, 2) or not np.isfinite(points).all() or np.any(points < 0) or np.any(points > 1):
        raise ValueError("Boundary JSON must contain exactly two normalized [x, y] points between 0 and 1.")
    height, width = frame.shape[:2]
    line = (points * [width, height]).astype(np.int32)
    if np.linalg.norm(line[1] - line[0]) < 20:
        raise ValueError("Boundary must be at least 20 pixels long; redraw it.")
    return line


def beep():
    try:
        import winsound
        winsound.Beep(1100, 250)
    except (ImportError, RuntimeError):
        print("\a", end="", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    local_model = Path(__file__).resolve().parent / "models" / "yolo26n.pt"
    parser.add_argument("--source", default="0", help="Camera number, video file, or RTSP URL")
    parser.add_argument("--model", default=str(local_model) if local_model.exists() else "yolo26n.pt")
    parser.add_argument("--sahi", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--slice-size", type=int, default=256)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.10)
    parser.add_argument("--device", default=None, help="cpu or 0 for NVIDIA GPU")
    parser.add_argument("--line", type=Path, default=Path("border_line.json"))
    parser.add_argument("--log", type=Path, default=Path("border_alerts.jsonl"))
    parser.add_argument("--margin", type=float, default=5, help="Ignore jitter within this many pixels of the line")
    parser.add_argument("--confirm-frames", type=int, default=2)
    parser.add_argument("--max-gap", type=int, default=5, help="Reset crossing history after this many missed frame intervals")
    parser.add_argument("--redraw", action="store_true")
    parser.add_argument("--mute", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0)
    args = parser.parse_args(argv)
    if args.headless and (args.redraw or not args.line.exists()):
        parser.error("--headless requires a saved --line and cannot use --redraw")
    if (args.imgsz < 32 or args.slice_size < 32 or not 0 < args.conf <= 1
            or not math.isfinite(args.margin) or args.margin < 0 or args.confirm_frames < 1
            or args.max_gap < 1 or args.max_frames < 0):
        parser.error("Invalid size, confidence, margin, confirmation, gap, or frame limit")
    cap = cv2.VideoCapture(int(args.source) if args.source.isdecimal() else args.source)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    try:
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"Cannot read source: {args.source}")

        def resize(image):
            height, width = image.shape[:2]
            return cv2.resize(image, (960, round(height * 960 / width))) if width > 960 else image

        frame = resize(frame)
        if not args.headless:
            cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        line = load_line(args.line, frame) if args.line.exists() and not args.redraw else draw_line(frame, args.line)
        if line is None:
            return
        monitor = CrossingMonitor(line, args.margin, args.confirm_frames, args.max_gap)
        print("Loading SAHI + YOLO26..." if args.sahi else "Loading YOLO26...", flush=True)
        detector = PersonDetector(args)
        args.log.parent.mkdir(parents=True, exist_ok=True)
        frame_number, fps = 0, 0.0
        alert_until, last_beep = 0.0, 0.0
        alert_text = ""
        print(f"Monitoring boundary. R redraw | Q quit. Events: {args.log}", flush=True)
        while True:
            started = time.perf_counter()
            tracks = detector.predict(frame)
            frame_number += 1
            display = frame.copy()
            paint_line(display, line)
            for track in tracks:
                x1, y1, x2, y2 = map(int, track[:4])
                person_id = int(track[4])
                foot = ((x1 + x2) / 2, float(y2))
                direction = monitor.update(person_id, foot, frame_number)
                if direction:
                    event = {"time": datetime.now().astimezone().isoformat(timespec="seconds"),
                             "event": "boundary_crossed", "direction": direction,
                             "person_id": person_id, "frame": frame_number,
                             "foot": list(foot), "line_file": str(args.line)}
                    with args.log.open("a", encoding="utf-8") as log:
                        log.write(json.dumps(event) + "\n")
                    alert_text = f"Person #{person_id}: {direction.replace('_', ' ')}"
                    print(f"ALERT: {alert_text} | frame {frame_number}", flush=True)
                    alert_until = time.monotonic() + 2
                    if not args.mute and time.monotonic() - last_beep > 0.5:
                        threading.Thread(target=beep, daemon=True).start()
                        last_beep = time.monotonic()
                color = (40, 40, 255) if direction else (80, 230, 80)
                cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
                cv2.circle(display, tuple(map(int, foot)), 4, color, -1)
                cv2.putText(display, f"Person {person_id}", (x1, max(18, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
            monitor.expire(frame_number)
            elapsed = max(time.perf_counter() - started, 1e-6)
            fps = 1 / elapsed if not fps else 0.9 * fps + 0.1 / elapsed
            active_alert = time.monotonic() < alert_until
            cv2.rectangle(display, (0, 0), (display.shape[1], 65), (30, 30, 150) if active_alert else (35, 35, 35), -1)
            cv2.putText(display, alert_text if active_alert else "Boundary monitoring active", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(display, f"A -> B: {monitor.counts['A_TO_B']} | B -> A: {monitor.counts['B_TO_A']} | Processing FPS: {fps:.1f}",
                        (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            if not args.headless:
                cv2.imshow(WINDOW, display)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
                if key == ord("r"):
                    line = draw_line(frame, args.line)
                    if line is None:
                        break
                    monitor = CrossingMonitor(line, args.margin, args.confirm_frames, args.max_gap)
                    alert_until = 0
            if args.max_frames and frame_number >= args.max_frames:
                break
            ok, frame = cap.read()
            if not ok:
                print("Video ended or source disconnected.")
                break
            frame = resize(frame)
        print(f"Processed {frame_number} frames | Crossings: {monitor.counts} | Processing FPS: {fps:.1f}")
    finally:
        cap.release()
        if not args.headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
