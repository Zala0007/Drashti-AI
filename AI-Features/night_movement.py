"""Standalone low-light motion alerts for a stationary visible-light or IR camera."""

import argparse
import json
import math
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

WINDOW = "Night Movement Detection"


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
        if (timestamp - self.pending_since >= self.confirm_seconds
                and timestamp - self.last_alert >= self.cooldown):
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
            history=300, varThreshold=threshold, detectShadows=True,
        )
        self.previous = None
        self.open_kernel = np.ones((3, 3), np.uint8)
        self.close_kernel = np.ones((5, 5), np.uint8)

    def reset(self):
        self.background = cv2.createBackgroundSubtractorMOG2(
            history=300, varThreshold=self.threshold, detectShadows=True,
        )
        self.previous = None

    def detect(self, frame):
        # Detection uses denoised original pixels. Brightening is display-only,
        # so the display enhancement does not amplify sensor noise for MOG2.
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        light_change = (0.0 if self.previous is None else
                        abs(float(np.median(gray.astype(np.int16) - self.previous.astype(np.int16)))))
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


def beep():
    try:
        import winsound
        winsound.Beep(1000, 250)
    except (ImportError, RuntimeError):
        print("\a", end="", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="0", help="Webcam index, video file, or RTSP URL")
    parser.add_argument("--min-area", type=int, default=120, help="Minimum moving region area in resized-image pixels")
    parser.add_argument("--threshold", type=float, default=25, help="MOG2 threshold; higher rejects more noise")
    parser.add_argument("--gamma", type=float, default=1.8, help="Display brightening; 1 disables brightening")
    parser.add_argument("--warmup", type=float, default=2, help="Seconds to learn the background before alerts")
    parser.add_argument("--confirm-seconds", type=float, default=0.35)
    parser.add_argument("--clear-seconds", type=float, default=1)
    parser.add_argument("--cooldown", type=float, default=3)
    parser.add_argument("--log", type=Path, default=Path("night_alerts.jsonl"))
    parser.add_argument("--show-mask", action="store_true", help="Show foreground mask beside the video")
    parser.add_argument("--mute", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0)
    args = parser.parse_args(argv)
    numeric = (args.threshold, args.gamma, args.warmup, args.confirm_seconds,
               args.clear_seconds, args.cooldown)
    if (not all(math.isfinite(value) for value in numeric) or args.threshold <= 0
            or args.gamma <= 0 or args.min_area < 1
            or min(args.warmup, args.confirm_seconds, args.clear_seconds, args.cooldown) < 0
            or args.max_frames < 0):
        parser.error("Use positive area/threshold/gamma and nonnegative timing values")

    is_video = Path(args.source).is_file()
    source = int(args.source) if args.source.isdecimal() else args.source
    cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open source: {args.source}")
        source_fps = cap.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(source_fps) or source_fps <= 0:
            source_fps = 30.0
            if is_video:
                print("Video FPS unavailable; using 30 FPS for event timing.")
        detector = MotionDetector(args.min_area, args.threshold)
        gate = MotionGate(args.confirm_seconds, args.clear_seconds, args.cooldown)
        gamma_table = np.clip(((np.arange(256) / 255.0) ** (1.0 / args.gamma)) * 255, 0, 255).astype(np.uint8)
        args.log.parent.mkdir(parents=True, exist_ok=True)
        frame_number, alert_count = 0, 0
        fps = 0.0
        start_time = time.monotonic()
        warmup_until = args.warmup
        previous_timestamp = -1.0
        previous_shape = None
        mode = "visible movement"
        print(f"Monitoring {mode}. Keep the camera stationary. Alerts: {args.log}", flush=True)
        print("Q: quit | R: relearn background | E: toggle brightening", flush=True)
        enhanced = True
        if not args.headless:
            cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        while True:
            ok, frame = cap.read()
            if not ok:
                if frame_number == 0:
                    raise RuntimeError(f"Cannot read a frame from source: {args.source}")
                print("Video ended or camera disconnected.")
                break
            started = time.perf_counter()
            frame_number += 1
            if is_video:
                position = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                timestamp = (position if math.isfinite(position) and position > previous_timestamp
                             else max((frame_number - 1) / source_fps, previous_timestamp + 1 / source_fps))
            else:
                timestamp = time.monotonic() - start_time
            previous_timestamp = timestamp
            height, width = frame.shape[:2]
            if width > 960:
                frame = cv2.resize(frame, (960, round(height * 960 / width)))
            if previous_shape is not None and frame.shape != previous_shape:
                detector.reset()
                gate.reset()
                warmup_until = timestamp + args.warmup
            previous_shape = frame.shape
            regions, mask, suppressed = detector.detect(frame)
            warming = timestamp < warmup_until
            display = cv2.LUT(frame, gamma_table) if enhanced else frame.copy()
            if warming or suppressed:
                gate.reset()
                candidates = []
            else:
                candidates = regions
                if gate.update(bool(candidates), timestamp):
                    alert_count += 1
                    event = {"time": datetime.now().astimezone().isoformat(timespec="seconds"),
                             "event": "movement_detected",
                             "frame": frame_number, "elapsed_seconds": round(timestamp, 3),
                             "time_basis": "video" if is_video else "live",
                             "regions": [list(box) for box in candidates]}
                    with args.log.open("a", encoding="utf-8") as log:
                        log.write(json.dumps(event) + "\n")
                    print(f"ALERT: {mode} at {timestamp:.2f}s | {len(candidates)} region(s)", flush=True)
                    if not args.mute:
                        threading.Thread(target=beep, daemon=True).start()
            for x1, y1, x2, y2 in candidates:
                color = (40, 40, 255) if gate.active else (0, 220, 255)
                cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
            elapsed = max(time.perf_counter() - started, 1e-6)
            fps = 1 / elapsed if not fps else 0.9 * fps + 0.1 / elapsed
            if warming:
                status = f"Learning background: {max(0, warmup_until - timestamp):.1f}s"
            elif suppressed:
                status = "Scene / lighting change: alert suppressed"
            elif gate.active:
                status = "ALERT: MOVEMENT"
            else:
                status = "Checking movement..." if candidates else "Monitoring"
            cv2.rectangle(display, (0, 0), (display.shape[1], 66), (30, 30, 150) if gate.active else (35, 35, 35), -1)
            cv2.putText(display, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(display, f"Events: {alert_count} | Processing FPS: {fps:.1f} | Brightening: {'on' if enhanced else 'off'}",
                        (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            if not args.headless:
                if args.show_mask:
                    display = np.hstack([display, cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)])
                cv2.imshow(WINDOW, display)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
                if key == ord("e"):
                    enhanced = not enhanced
                if key == ord("r"):
                    detector.reset()
                    gate.reset()
                    warmup_until = timestamp + args.warmup
            if args.max_frames and frame_number >= args.max_frames:
                break
        print(f"Processed {frame_number} frames | Alerts: {alert_count} | Processing FPS: {fps:.1f}")
    finally:
        cap.release()
        if not args.headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
