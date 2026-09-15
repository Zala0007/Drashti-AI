"""Detect objects and draw their movement paths with YOLO26 tracking."""

import argparse
import math
import os
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
WINDOW = "Object Detection and Movement Paths"


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


def draw_track(canvas, box, label, color, points=None):
    x1, y1, x2, y2 = map(int, box)
    if points:
        if len(points) > 1:
            trail = np.asarray(points, np.int32).reshape(-1, 1, 2)
            cv2.polylines(canvas, [trail], False, color, 2, cv2.LINE_AA)
        cv2.circle(canvas, points[-1], 4, color, -1)
    cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
    (width, height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    left = max(0, min(x1, canvas.shape[1] - width - 8))
    bottom = y1 - 5 if y1 >= height + baseline + 10 else y1 + height + baseline + 10
    bottom = min(canvas.shape[0] - baseline - 3, max(height + 5, bottom))
    cv2.rectangle(canvas, (left, bottom - height - 5), (left + width + 8, bottom + baseline + 3), color, -1)
    cv2.putText(canvas, label, (left + 4, bottom), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (15, 15, 15), 1, cv2.LINE_AA)


def default_weights():
    for path in (ROOT / "models" / "yolo26n.pt", ROOT / "yolo26n.pt"):
        if path.is_file():
            return str(path)
    return "yolo26n.pt"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Video path, RTSP URL, or webcam index")
    parser.add_argument("--weights", default=default_weights(), help="YOLO model weights")
    parser.add_argument("--classes", type=int, nargs="+", help="Class IDs to keep; omitted means all model classes")
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default=None, help="cpu or 0 for NVIDIA GPU")
    parser.add_argument("--trail", type=int, default=30, help="Recent center points per object")
    parser.add_argument("--save", type=Path, help="Optional annotated MP4 output; must be a new file")
    parser.add_argument("--no-show", action="store_true", help="Run without opening a window")
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after N frames; 0 processes the whole video")
    args = parser.parse_args(argv)
    if not 0 < args.conf <= 1 or args.imgsz < 32 or args.trail < 2 or args.max_frames < 0:
        parser.error("Use confidence in (0,1], imgsz >= 32, trail >= 2, and max-frames >= 0")
    if args.classes is not None and any(class_id < 0 for class_id in args.classes):
        parser.error("Class IDs must be nonnegative")
    if args.save:
        if args.save.resolve() == Path(args.source).resolve():
            parser.error("Output video must be different from the input video")
        if args.save.exists():
            parser.error(f"Output already exists: {args.save}. Choose a new --save path.")
        if args.save.suffix.lower() != ".mp4":
            parser.error("Use an .mp4 file for --save")

    source = int(args.source) if args.source.isdecimal() else args.source
    capture = cv2.VideoCapture(source)
    writer = None
    try:
        if not capture.isOpened():
            raise RuntimeError(f"Cannot open source: {args.source}")
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"Cannot read a frame from: {args.source}")
        source_fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(source_fps) or source_fps <= 0:
            source_fps = 30.0
        from ultralytics import YOLO
        from ultralytics.utils.plotting import colors

        # Ultralytics sanitizes apostrophes in absolute paths. A relative path
        # works for this workspace's existing weights.
        weights = os.path.relpath(args.weights) if Path(args.weights).is_file() else args.weights
        print(f"Loading {args.weights}...", flush=True)
        model = YOLO(weights)
        if args.classes is not None and any(class_id not in model.names for class_id in args.classes):
            raise ValueError("Requested class ID is not present in this model")
        paths = MovementPaths(args.trail)
        frame_number, fps = 0, 0.0
        output_shape = frame.shape[:2]
        if args.save:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            height, width = output_shape
            writer = cv2.VideoWriter(str(args.save), cv2.VideoWriter_fourcc(*"mp4v"), source_fps, (width, height))
            if not writer.isOpened():
                raise RuntimeError(f"Cannot write video: {args.save}")
        if not args.no_show:
            cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        print("Tracking objects. Q / Escape: quit.", flush=True)
        while True:
            started = time.perf_counter()
            if frame.shape[:2] != output_shape:
                raise RuntimeError("Video dimensions changed; restart tracking with the new source dimensions")
            result = model.track(frame, persist=True, tracker="botsort.yaml", classes=args.classes,
                                 conf=args.conf, imgsz=args.imgsz, device=args.device, verbose=False)[0]
            frame_number += 1
            canvas = frame.copy()
            boxes = result.boxes
            if boxes is not None:
                coordinates = boxes.xyxy.cpu().numpy()
                scores = boxes.conf.cpu().tolist()
                classes = boxes.cls.int().cpu().tolist()
                ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [None] * len(boxes)
                for box, score, class_id, track_id in zip(coordinates, scores, classes, ids):
                    points = paths.update(track_id, box, frame_number) if track_id is not None else None
                    identity = f" #{track_id}" if track_id is not None else ""
                    label = f"{result.names[class_id]}{identity} {score:.2f}"
                    draw_track(canvas, box, label, colors(track_id if track_id is not None else class_id, True), points)
            paths.expire(frame_number)
            elapsed = max(time.perf_counter() - started, 1e-6)
            fps = 1 / elapsed if not fps else 0.9 * fps + 0.1 / elapsed
            cv2.putText(canvas, f"Frame {frame_number} | Processing FPS: {fps:.1f}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
            if writer is not None:
                writer.write(canvas)
            if not args.no_show:
                cv2.imshow(WINDOW, canvas)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
            if args.max_frames and frame_number >= args.max_frames:
                break
            ok, frame = capture.read()
            if not ok:
                break
        print(f"Processed {frame_number} frames | Processing FPS: {fps:.1f}")
        if args.save:
            print(f"Saved annotated video: {args.save.resolve()}")
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        if not args.no_show:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
