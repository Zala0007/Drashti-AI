"""Draw a polygon and alert when a tracked person enters it."""

import argparse
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from ultralytics import YOLO
from ultralytics.engine.results import Boxes
from ultralytics.trackers.byte_tracker import BYTETracker

WINDOW = "YOLO Virtual Fence"
LOCAL_MODEL = Path(__file__).resolve().parent / "models" / "yolo26n.pt"


class PersonDetector:
    """Merge SAHI detections before tracking, in full-frame coordinates."""

    def __init__(self, args):
        self.args = args
        # Ultralytics strips apostrophes from model paths; use a relative path
        # for existing weights in this workspace (whose name contains one).
        model_path = os.path.relpath(args.model) if Path(args.model).is_file() else args.model
        self.model = YOLO(model_path)
        self.sahi_model = None
        if args.sahi:
            from sahi import AutoDetectionModel

            device = args.device
            if device is not None and str(device).isdecimal():
                device = f"cuda:{device}"
            self.sahi_model = AutoDetectionModel.from_pretrained(
                model_type="ultralytics", model=self.model,
                confidence_threshold=args.conf, device=device,
                image_size=args.imgsz,
            )
            # Only request people from each tile and the full-frame pass.
            self.model.overrides["classes"] = [0]
        # Match the detector threshold so 0.10-confidence SAHI detections
        # can start tracks. IoU matching avoids suppressing low-score tracks.
        self.tracker = BYTETracker(SimpleNamespace(
            track_high_thresh=args.conf, track_low_thresh=min(0.1, args.conf),
            new_track_thresh=args.conf, track_buffer=30, match_thresh=0.8,
            fuse_score=False,
        ))

    @staticmethod
    def person_boxes(predictions, shape):
        rows = [[*pred.bbox.to_xyxy(), pred.score.value, 0]
                for pred in predictions if pred.category.id == 0]
        return Boxes(np.asarray(rows, dtype=np.float32).reshape(-1, 6), shape)

    def predict(self, frame):
        if self.sahi_model is not None:
            from sahi.predict import get_sliced_prediction

            prediction = get_sliced_prediction(
                cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), self.sahi_model,
                slice_height=self.args.slice_height, slice_width=self.args.slice_width,
                overlap_height_ratio=self.args.overlap, overlap_width_ratio=self.args.overlap,
                perform_standard_pred=True, verbose=0,
            )
            boxes = self.person_boxes(prediction.object_prediction_list, frame.shape[:2])
        else:
            boxes = self.model.predict(
                frame, classes=[0], conf=self.args.conf, imgsz=self.args.imgsz,
                device=self.args.device, verbose=False,
            )[0].boxes.cpu().numpy()
        # Advance on empty frames too, so lost tracks age out correctly.
        tracks = self.tracker.update(boxes, frame)
        if not len(tracks):
            return Boxes(np.empty((0, 7), dtype=np.float32), frame.shape[:2])
        # ByteTrack returns x1,y1,x2,y2,id,score,class,detection_index.
        return Boxes(tracks[:, :7], frame.shape[:2])


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


def beep():
    try:
        import winsound
        winsound.Beep(1100, 250)
    except (ImportError, RuntimeError):
        print("\a", end="", flush=True)


def draw_fence(frame, path):
    points = []

    def mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()

    cv2.setMouseCallback(WINDOW, mouse)
    try:
        while True:
            preview = frame.copy()
            if points:
                cv2.polylines(preview, [np.array(points, np.int32)], len(points) >= 3, (0, 220, 255), 2)
            for point in points:
                cv2.circle(preview, point, 5, (0, 220, 255), -1)
            cv2.putText(preview, "Click corners | Right-click undo | Enter start | R reset | Q quit",
                        (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
            cv2.imshow(WINDOW, preview)
            key = cv2.waitKey(20) & 0xFF
            if key in (13, 10) and len(points) >= 3:
                polygon = np.array(points, np.int32)
                if abs(cv2.contourArea(polygon)) < 20:
                    print("Draw a fence with a nonzero area.")
                    continue
                height, width = frame.shape[:2]
                path.write_text(json.dumps([[x / width, y / height] for x, y in points]), encoding="utf-8")
                return polygon
            if key in (ord("r"), ord("R")):
                points.clear()
            if key in (27, ord("q")) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                return None
    finally:
        cv2.setMouseCallback(WINDOW, lambda *args: None)


def load_fence(path, frame):
    points = np.asarray(json.loads(path.read_text(encoding="utf-8")), dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
        raise ValueError("Fence JSON must contain at least three [x, y] normalized points.")
    if not np.isfinite(points).all() or np.any(points < 0) or np.any(points > 1):
        raise ValueError("Fence coordinates must be between 0 and 1.")
    height, width = frame.shape[:2]
    polygon = (points * [width, height]).astype(np.int32)
    if abs(cv2.contourArea(polygon)) < 20:
        raise ValueError("Fence area is too small.")
    return polygon


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="0", help="Webcam number, video path, or RTSP URL")
    parser.add_argument("--model", default=str(LOCAL_MODEL) if LOCAL_MODEL.exists() else "yolo26n.pt")
    parser.add_argument("--sahi", action=argparse.BooleanOptionalAction, default=True,
                        help="Use SAHI sliced YOLO26 detection (default); --no-sahi is faster")
    parser.add_argument("--slice-height", type=int, default=256)
    parser.add_argument("--slice-width", type=int, default=256)
    parser.add_argument("--overlap", type=float, default=0.2, help="Tile overlap ratio, from 0 to below 1")
    parser.add_argument("--imgsz", type=int, default=640, help="YOLO input size per tile; lower is faster")
    parser.add_argument("--conf", type=float, default=0.10)
    parser.add_argument("--device", default=None, help="cpu or 0 for NVIDIA GPU")
    parser.add_argument("--fence", type=Path, default=Path("fence.json"))
    parser.add_argument("--redraw", action="store_true")
    parser.add_argument("--mute", action="store_true")
    parser.add_argument("--headless", action="store_true", help="Use saved fence without a display")
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after N frames; 0 means unlimited")
    args = parser.parse_args()
    if args.headless and (args.redraw or not args.fence.exists()):
        parser.error("--headless requires an existing --fence and cannot use --redraw")
    if args.imgsz < 32 or not 0 < args.conf <= 1 or args.max_frames < 0:
        parser.error("Use imgsz >= 32, 0 < conf <= 1, and max-frames >= 0")
    if args.slice_height < 32 or args.slice_width < 32 or not 0 <= args.overlap < 1:
        parser.error("Use slice dimensions >= 32 and 0 <= overlap < 1")

    source = int(args.source) if args.source.isdecimal() else args.source
    cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if isinstance(source, int):
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
    try:
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"Cannot read video source: {args.source}")

        def resize(image):
            height, width = image.shape[:2]
            return cv2.resize(image, (960, round(height * 960 / width))) if width > 960 else image

        frame = resize(frame)
        if not args.headless:
            cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        polygon = (load_fence(args.fence, frame) if args.fence.exists() and not args.redraw
                   else draw_fence(frame, args.fence))
        if polygon is None:
            return

        mode = "SAHI sliced YOLO" if args.sahi else "Standard YOLO"
        print(f"Loading {mode}: {args.model}; first run may download weights.", flush=True)
        detector = PersonDetector(args)
        monitor = EntryMonitor()
        frame_number = 0
        alert_until = 0.0
        last_beep = 0.0
        fps = 0.0
        print("Monitoring. R: redraw fence | Q: quit. Alerts are saved to alerts.jsonl.", flush=True)
        while True:
            started = time.perf_counter()
            boxes = detector.predict(frame)
            frame_number += 1
            inside_count = 0
            overlay = frame.copy()
            cv2.fillPoly(overlay, [polygon], (0, 160, 240))
            display = cv2.addWeighted(overlay, 0.18, frame, 0.82, 0)
            cv2.polylines(display, [polygon], True, (0, 220, 255), 2)
            if boxes is not None:
                coordinates = boxes.xyxy
                ids = boxes.id.astype(int).tolist() if boxes.id is not None else [None] * len(coordinates)
                for bounds, person_id in zip(coordinates, ids):
                    x1, y1, x2, y2 = map(int, bounds)
                    foot = ((x1 + x2) // 2, y2)
                    inside = cv2.pointPolygonTest(polygon, foot, False) >= 0
                    inside_count += int(inside)
                    if person_id is not None and monitor.update(person_id, inside, frame_number):
                        event = {"time": datetime.now().astimezone().isoformat(timespec="seconds"),
                                 "event": "person_entered", "person_id": person_id, "frame": frame_number}
                        print(f"ALERT: Person #{person_id} entered the fence at {event['time']}", flush=True)
                        with Path("alerts.jsonl").open("a", encoding="utf-8") as log:
                            log.write(json.dumps(event) + "\n")
                        alert_until = time.monotonic() + 2
                        if not args.mute and time.monotonic() - last_beep > 0.5:
                            threading.Thread(target=beep, daemon=True).start()
                            last_beep = time.monotonic()
                    color = (40, 40, 255) if inside else (80, 230, 80)
                    cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
                    cv2.circle(display, foot, 5, color, -1)
                    cv2.putText(display, f"Person {person_id if person_id is not None else '?'}",
                                (x1, max(18, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
            monitor.expire(frame_number)
            elapsed = time.perf_counter() - started
            fps = 1 / elapsed if not fps else 0.9 * fps + 0.1 / elapsed
            alert = time.monotonic() < alert_until
            cv2.rectangle(display, (0, 0), (display.shape[1], 48), (30, 30, 180) if alert else (35, 35, 35), -1)
            status = "ALERT: PERSON ENTERED!" if alert else "Fence active"
            cv2.putText(display, f"{status} | Inside: {inside_count} | Processing FPS: {fps:.1f}",
                        (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            if not args.headless:
                cv2.imshow(WINDOW, display)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
                if key == ord("r"):
                    polygon = draw_fence(frame, args.fence)
                    if polygon is None:
                        break
                    monitor = EntryMonitor()
                    alert_until = 0
            if args.max_frames and frame_number >= args.max_frames:
                break
            ok, frame = cap.read()
            if not ok:
                print("Video ended or source disconnected.")
                break
            frame = resize(frame)
        print(f"Processed {frame_number} frames. Final processing rate: {fps:.1f} FPS.")
    finally:
        cap.release()
        if not args.headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
