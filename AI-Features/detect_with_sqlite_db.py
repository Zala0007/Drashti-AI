"""
Track, crop and store object crops in SQLite using Ultralytics YOLO26. Every tracked
detection is cropped from its frame, JPEG-encoded and written to a SQLite database 
alongside its track ID, class, confidence, box geometry and source frame, making the 
database a self-contained, queryable archive that needs no companion image folder.

Usage
    python detect_with_sqlite_db.py --source traffic.mp4
    python detect_with_sqlite_db.py --source traffic.mp4 --classes 0 2
        
Note:
    pip install ultralytics sqlite3
"""

from __future__ import annotations

import cv2
import sqlite3
import argparse
import numpy as np
from pathlib import Path
from ultralytics import YOLO
from collections import defaultdict, deque

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"
DEFAULT_YOLO_MODEL = MODELS_DIR / "yolo26n.pt"

BOX_THICKNESS = 4
TEXT_SCALE = 1.2
TEXT_THICKNESS = 2
TEXT_PADDING = 10
CIRCLE_RADIUS = 4
POLYLINE_THICKNESS = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT    NOT NULL,
    frame        INTEGER NOT NULL,
    time_ms      REAL    NOT NULL,
    track_id     INTEGER,
    class_id     INTEGER NOT NULL,
    class_name   TEXT    NOT NULL,
    confidence   REAL    NOT NULL,
    x1           REAL    NOT NULL,
    y1           REAL    NOT NULL,
    x2           REAL    NOT NULL,
    y2           REAL    NOT NULL,
    width        INTEGER NOT NULL,
    height       INTEGER NOT NULL,
    crop         BLOB    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_class ON detections(class_name);
CREATE INDEX IF NOT EXISTS idx_frame ON detections(source, frame);
-- Non-unique: one row per sighting, so a track ID repeats once per frame it appears in.
CREATE INDEX IF NOT EXISTS idx_track ON detections(source, track_id);
CREATE INDEX IF NOT EXISTS idx_detection_latest
    ON detections(created_at DESC, id DESC);
"""

COLUMNS = (
    "source, frame, time_ms, track_id," 
    "class_id, class_name, confidence,"
    "x1, y1, x2, y2, width, height, crop"
)
PLACEHOLDERS = ", ".join("?" * 14)

INSERT = f"INSERT INTO detections ({COLUMNS}) VALUES ({PLACEHOLDERS})"


class CropDatabase:
    """
    A SQLite archive of JPEG-encoded crops and their metadata, one row per tracked sighting.
    Rows are buffered and written with a single ``executemany`` per batch. Committing once
    per detection would dominate runtime, since each commit forces a disk sync.
    """
    def __init__(self, path: str | Path, batch_size: int = 200) -> None:
        """Open (or create) the database and apply the schema."""
        self.connection = sqlite3.connect(str(path))
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.executescript(SCHEMA)
        self._batch_size = batch_size
        self._buffer: list[tuple] = []

    def add(self, record: tuple) -> None:
        """Buffer one detection row, flushing automatically when the batch fills."""
        self._buffer.append(record)
        if len(self._buffer) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        """Write and commit any buffered rows."""
        if self._buffer:
            self.connection.executemany(INSERT, self._buffer)
            self.connection.commit()
            self._buffer.clear()

    def summary(self) -> list[tuple]:
        """Summarise stored crops per class."""
        return self.connection.execute(
            """
            SELECT class_name, COUNT(*), ROUND(AVG(confidence), 3), SUM(LENGTH(crop))
            FROM detections GROUP BY class_name ORDER BY COUNT(*) DESC
            """
        ).fetchall()

    def export(self, directory: str | Path, class_name: str | None = None) -> int:
        """Write stored crops back out as ``.jpg`` files, one sub-folder per class."""
        query = "SELECT id, class_name, frame, track_id, crop FROM detections"
        parameters: tuple = ()
        if class_name:
            query += " WHERE class_name = ?"
            parameters = (class_name,)
        directory = Path(directory)
        written = 0
        for row_id, name, frame, track_id, blob in self.connection.execute(query, parameters):
            folder = directory / name
            folder.mkdir(parents=True, exist_ok=True)
            tag = f"track{track_id}" if track_id is not None else f"id{row_id}"
            (folder / f"frame{frame:06d}_{tag}.jpg").write_bytes(blob)
            written += 1
        return written

    def close(self) -> None:
        """Flush pending rows and close the connection."""
        self.flush()
        self.connection.close()

    def __enter__(self) -> CropDatabase:
        """Enter the context manager."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Flush and close on exit, including when the body raised."""
        self.close()


def crop_box(frame: np.ndarray, box: np.ndarray, padding: float = 0.0):
    """Cut a padded, bounds-clamped crop out of a frame."""
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = box
    pad_x, pad_y = (x2 - x1) * padding, (y2 - y1) * padding
    x1 = max(0, int(round(x1 - pad_x)))
    y1 = max(0, int(round(y1 - pad_y)))
    x2 = min(width, int(round(x2 + pad_x)))
    y2 = min(height, int(round(y2 + pad_y)))
    if x2 <= x1 or y2 <= y1:
        return None, (x1, y1, x2, y2)
    return frame[y1:y2, x1:x2], (x1, y1, x2, y2)


def draw_track(
    canvas: np.ndarray, 
    box: np.ndarray, 
    label: str, 
    color: tuple, 
    points=None, 
    txt_color=None):
    """Draw one box, its label plate and its trajectory onto ``canvas``, in place."""
    x1, y1, x2, y2 = (int(value) for value in box)

    if points and len(points) > 1:
        trail = np.array(points, np.int32).reshape((-1, 1, 2))
        cv2.polylines(canvas, [trail], False, color, POLYLINE_THICKNESS)
        cv2.circle(canvas, points[-1], CIRCLE_RADIUS, color, -1)

    cv2.rectangle(canvas, (x1, y1), (x2, y2), color, BOX_THICKNESS)

    (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, TEXT_SCALE, TEXT_THICKNESS)
    plate = text_h + TEXT_PADDING * 2
    # Objects touching the top edge would otherwise have their label drawn off-frame,
    # so the plate drops inside the box instead of sitting above it.
    top = y1 if y1 >= plate else y1 + plate
    cv2.rectangle(canvas, (x1, top - plate), (x1 + text_w + TEXT_PADDING * 2, top), color, -1)
    cv2.putText(
        canvas, label, (x1 + TEXT_PADDING, top - TEXT_PADDING),
        cv2.FONT_HERSHEY_SIMPLEX, TEXT_SCALE, txt_color, TEXT_THICKNESS, cv2.LINE_AA,
    )


def detect_and_store(
    source: str | Path,
    database: str | Path = "crops.db",
    weights: str | Path = DEFAULT_YOLO_MODEL,
    classes: list[int] | None = None,
    conf: float = 0.4,
    padding: float = 0.05,
    min_size: int = 24,
    quality: int = 90,
    show: bool = True,
    save: str | Path | None = "output.mp4",
    trail: int = 30,
) -> int:
    """
    Track objects with YOLO26, display them and archive every tracked crop in SQLite. Each
    sighting is stored as its own row, so a track's full history is recoverable with
    ``SELECT * FROM detections WHERE track_id = ? ORDER BY frame``.
    """
    capture = cv2.VideoCapture(str(source))
    fps = (capture.get(cv2.CAP_PROP_FPS) or 30.0) if capture.isOpened() else 30.0
    capture.release()

    model = YOLO(str(weights))
    stored, name = 0, str(source)
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    # Frames are only annotated when something consumes them — a window, a file, or both.
    draw = show or save is not None
    writer = None
    if save is not None:
        Path(save).parent.mkdir(parents=True, exist_ok=True)
    # Box-centre history per track ID, capped so a trail slides out of view behind the
    # object rather than growing for the whole video.
    trails: dict[int, deque] = defaultdict(lambda: deque(maxlen=trail))

    with CropDatabase(database) as db:
        stream = model.track(
            source=str(source), 
            stream=True, 
            persist=True, 
            conf=conf, 
            classes=classes, 
            verbose=False
        )
        try:
            for index, result in enumerate(stream):
                frame = result.orig_img
                boxes = result.boxes
                # A copy, so the crops written to the database stay clean, unannotated pixels.
                annotated = frame.copy() if draw else None

                if boxes is not None and len(boxes):
                    xyxy = boxes.xyxy.cpu().numpy()
                    confidences = boxes.conf.cpu().tolist()
                    class_ids = boxes.cls.int().cpu().tolist()

                    track_ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [None] * len(xyxy)

                    for box, score, class_id, track_id in zip(xyxy, confidences, class_ids, track_ids):
                        if draw:
                            color = (0, 255, 0)
                            txt_color = (104, 31, 17)
                            label = result.names[class_id]
                            points = None
                            if track_id is not None:
                                label = f"{label}#{track_id}"
                                trails[track_id].append((int((box[0] + box[2]) / 2), int((box[1] + box[3]) / 2)))
                                points = trails[track_id]
                            draw_track(annotated, box, label, color, points, txt_color)

                        crop, (x1, y1, x2, y2) = crop_box(frame, box, padding)
                        if crop is None or min(crop.shape[:2]) < min_size:
                            continue
                        ok, buffer = cv2.imencode(".jpg", crop, encode_params)
                        if not ok:
                            continue
                        db.add(
                            (
                                name, index, index / fps * 1000.0, track_id, class_id,
                                result.names[class_id], float(score),
                                float(x1), float(y1), float(x2), float(y2),
                                crop.shape[1], crop.shape[0], sqlite3.Binary(buffer.tobytes()),
                            )
                        )
                        stored += 1

                if save is not None:
                    if writer is None:  # opened here, since the frame size is only known now
                        height, width = annotated.shape[:2]
                        writer = cv2.VideoWriter(
                            str(save), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
                        )
                        # A writer that fails to open still accepts write() calls and leaves a
                        # 0-byte file behind, so the failure has to be raised here or not at all.
                        if not writer.isOpened():
                            raise RuntimeError(f"could not open {save} for writing")
                    writer.write(annotated)

                if show:
                    cv2.imshow("YOLO26 tracking", annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
        finally:
            # Without an explicit release the MP4 is left without its index and won't play,
            # so this has to survive an early `q`, a stream error or a Ctrl-C alike.
            if writer is not None:
                writer.release()
            if show:
                cv2.destroyAllWindows()
    return stored


def print_summary(database: str | Path) -> None:
    """Print a per-class breakdown of what is stored in a database."""
    with CropDatabase(database) as db:
        rows = db.summary()
        if not rows:
            print("No crops stored.")
            return
        print(f"{'class':<16}{'count':>8}{'avg conf':>10}{'size':>12}")
        for class_name, count, average, total_bytes in rows:
            print(f"{class_name:<16}{count:>8}{average:>10.3f}{total_bytes / 1e6:>11.2f}MB")


def main() -> None:
    """Parse command-line arguments and run detection, summary or export."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", help="Video, image, folder, RTSP URL, or webcam index")
    parser.add_argument("--db", default="crops.db", help="SQLite database path")
    parser.add_argument(
        "--weights",
        type=Path,
        default=DEFAULT_YOLO_MODEL,
        help="YOLO26 checkpoint",
    )
    parser.add_argument("--classes", type=int, nargs="*", help="Class IDs to keep, e.g. 0 2")
    parser.add_argument("--conf", type=float, default=0.4, help="Confidence threshold")
    parser.add_argument("--padding", type=float, default=0.05, help="Crop padding fraction")
    parser.add_argument("--min-size", type=int, default=24, help="Minimum crop side in pixels")
    parser.add_argument("--no-show", dest="show", action="store_false", help="Run without a window")
    parser.add_argument("--save", default="output.mp4", help="Annotated video output path")
    parser.add_argument("--no-save", dest="save", action="store_const", const=None,
                        help="Skip writing the annotated video")
    parser.add_argument("--trail", type=int, default=30, help="Track trail length in frames")
    parser.add_argument("--summary", action="store_true", help="Print stored crop counts")
    parser.add_argument("--export", metavar="DIR", help="Export stored crops to a folder")
    parser.add_argument("--class", dest="class_name", help="Limit --export to one class")
    args = parser.parse_args()

    if args.source:
        stored = detect_and_store(
            source=args.source, 
            database=args.db, 
            weights=args.weights,
            classes=args.classes, 
            conf=args.conf, 
            padding=args.padding, 
            min_size=args.min_size,
            show=args.show,
            save=args.save,
            trail=args.trail,
        )
        print(f"Stored {stored} tracked crops in {args.db}")
        if args.save:
            print(f"Wrote annotated video to {Path(args.save).resolve()}")
    if args.summary:
        print_summary(args.db)
    if args.export:
        with CropDatabase(args.db) as db:
            print(f"Exported {db.export(args.export, args.class_name)} crops to {args.export}")
    if not (args.source or args.summary or args.export):
        parser.error("give --source to ingest, or --summary / --export to inspect")


if __name__ == "__main__":
    main()
