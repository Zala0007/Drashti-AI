"""Detect and read Indian number plates in images, folders, and videos.

The default pipeline uses the project plate-specific YOLO detector to locate plates and
Google Cloud Vision to read the resulting crops. Use ``--no-detector`` only when the
input images are already tightly cropped number plates.

Examples:
    python anpr_video_detect.py --source vehicle.jpg --output annotated
    python anpr_video_detect.py --source plate.jpg --no-detector
    python anpr_video_detect.py --source plate_crops --json results.json
    python anpr_video_detect.py --source traffic.mp4 --output annotated.mp4 \
        --json results.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"
DEFAULT_DETECTOR = MODELS_DIR / "license_plate_detector.pt"
MODEL_REGISTRY = MODELS_DIR / "model_registry.json"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
GOOGLE_OCR_MODEL_ID = "google-cloud-vision:document-text-detection-v1"
GOOGLE_BATCH_LIMIT = 16
INDIAN_STATE_CODES = {
    "AN",
    "AP",
    "AR",
    "AS",
    "BR",
    "CG",
    "CH",
    "DD",
    "DL",
    "DN",
    "GA",
    "GJ",
    "HP",
    "HR",
    "JH",
    "JK",
    "KA",
    "KL",
    "LA",
    "LD",
    "MH",
    "ML",
    "MN",
    "MP",
    "MZ",
    "NL",
    "OD",
    "OR",
    "PB",
    "PY",
    "RJ",
    "SK",
    "TN",
    "TR",
    "TS",
    "UK",
    "UP",
    "WB",
}
ALPHA_CONFUSIONS = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
DIGIT_CONFUSIONS = {
    "O": "0",
    "Q": "0",
    "D": "0",
    "I": "1",
    "L": "1",
    "Z": "2",
    "S": "5",
    "G": "6",
    "B": "8",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def registered_detector() -> Path:
    """Return the checksum-verified active detector, or the stable baseline checkpoint."""
    if not MODEL_REGISTRY.is_file():
        return DEFAULT_DETECTOR
    try:
        registry = json.loads(MODEL_REGISTRY.read_text(encoding="utf-8"))
        active = registry["active_detector"]
        candidate = (MODELS_DIR / active["file"]).resolve()
        candidate.relative_to(MODELS_DIR.resolve())
        if candidate.is_file() and file_sha256(candidate) == active["sha256"]:
            return candidate
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        pass
    raise RuntimeError(
        f"ANPR model registry is invalid or its detector checksum does not match: {MODEL_REGISTRY}"
    )


def model_version(
    detector: Path | None, ocr_provider: str = GOOGLE_OCR_MODEL_ID
) -> str:
    detector_id = (
        "roi-only"
        if detector is None
        else f"{detector.stem}:{file_sha256(detector)[:12]}"
    )
    return f"detector={detector_id};ocr={ocr_provider}"


def prepare_plate_crop(image: np.ndarray, enhanced: bool = True) -> np.ndarray:
    """Upscale and clean a detector crop before sending it to Cloud Vision."""
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Plate crop must be a three-channel BGR image")
    height, width = image.shape[:2]
    if not height or not width:
        raise ValueError("Cannot recognize an empty plate crop")

    # Character confidence degrades quickly on tiny crops. Preserve aspect ratio
    # and use cubic interpolation until the crop is large enough for remote OCR.
    scale = max(1.0, 112.0 / height, 320.0 / width)
    scale = min(scale, 4.0)
    prepared = (
        cv2.resize(
            image,
            (round(width * scale), round(height * scale)),
            interpolation=cv2.INTER_CUBIC,
        )
        if scale > 1.0
        else image.copy()
    )
    if not enhanced:
        return prepared

    # CLAHE on luminance preserves character colour while improving local contrast.
    lab = cv2.cvtColor(prepared, cv2.COLOR_BGR2LAB)
    luminance, channel_a, channel_b = cv2.split(lab)
    luminance = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(luminance)
    contrast = cv2.cvtColor(
        cv2.merge((luminance, channel_a, channel_b)), cv2.COLOR_LAB2BGR
    )

    # A small unsharp mask makes strokes clearer after a distant plate is enlarged.
    blurred = cv2.GaussianBlur(contrast, (0, 0), 1.0)
    sharpened = cv2.addWeighted(contrast, 1.6, blurred, -0.6, 0)
    return sharpened


def _fit_plate_pattern(text: str, pattern: str) -> tuple[str, int] | None:
    """Fit OCR text to an ``A`` (letter) / ``9`` (digit) registration pattern."""
    if len(text) != len(pattern):
        return None
    corrected: list[str] = []
    edits = 0
    for character, expected in zip(text, pattern):
        if expected == "A":
            replacement = (
                character if character.isalpha() else ALPHA_CONFUSIONS.get(character)
            )
        else:
            replacement = (
                character if character.isdigit() else DIGIT_CONFUSIONS.get(character)
            )
        if replacement is None:
            return None
        corrected.append(replacement)
        edits += replacement != character
    candidate = "".join(corrected)
    if pattern.startswith("AA") and candidate[:2] not in INDIAN_STATE_CODES:
        return None
    if pattern == "99AA9999AA" and candidate[2:4] != "BH":
        return None
    return candidate, edits


def normalize_indian_plate(text: str) -> tuple[str, bool]:
    """Clean OCR output and correct common O/0, I/1-style position errors."""
    cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())
    if not cleaned:
        return "", False

    patterns = ["99AA9999AA"]  # Bharat-series registration, for example 22BH1234AA.
    patterns.extend(
        "AA" + "9" * district_digits + "A" * series_letters + "9999"
        for district_digits in (2, 1)
        for series_letters in (1, 2, 3)
    )
    # Document OCR can repeat the same line or retain a neighbouring character.
    # Evaluate bounded substrings so a valid registration is recovered without
    # accepting arbitrary unstructured OCR text as a plate.
    candidates = [cleaned]
    if len(cleaned) > min(map(len, patterns)):
        candidates.extend(
            cleaned[start : start + len(pattern)]
            for pattern in patterns
            for start in range(len(cleaned) - len(pattern) + 1)
        )
    matches = [
        (result[0], result[1], index)
        for index, candidate in enumerate(candidates)
        for pattern in patterns
        if (result := _fit_plate_pattern(candidate, pattern))
    ]
    if not matches:
        return cleaned, False
    corrected, edits, _ = min(matches, key=lambda item: (item[1], item[2]))
    # More than two substitutions usually means the OCR result is not a plate at all.
    return (corrected, True) if edits <= 2 else (cleaned, False)


def _cloud_vision_result(response: Any) -> tuple[str, float]:
    """Extract normalized text and a length-weighted confidence from a Vision response."""
    error = getattr(getattr(response, "error", None), "message", "")
    if error:
        raise RuntimeError(f"Google Cloud Vision OCR failed: {error}")
    annotation = getattr(response, "full_text_annotation", None)
    raw_text = str(getattr(annotation, "text", "") or "")
    normalized, valid_format = normalize_indian_plate(raw_text)
    if not normalized or not valid_format:
        return "", 0.0

    weighted_confidence = 0.0
    character_count = 0
    for page in getattr(annotation, "pages", ()):
        for block in getattr(page, "blocks", ()):
            for paragraph in getattr(block, "paragraphs", ()):
                for word in getattr(paragraph, "words", ()):
                    symbols = tuple(getattr(word, "symbols", ()))
                    weight = max(1, len(symbols))
                    confidence = float(getattr(word, "confidence", 0.0) or 0.0)
                    weighted_confidence += confidence * weight
                    character_count += weight
    confidence = weighted_confidence / character_count if character_count else 0.0
    return normalized, min(1.0, max(0.0, confidence))


class GoogleCloudVisionOCR:
    """Batch cropped plates through Google Cloud Vision document text detection."""

    def __init__(
        self,
        credentials: Path | None = None,
        timeout: float = 8.0,
        client: Any | None = None,
        vision_module: Any | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Google Cloud Vision timeout must be positive")
        self.timeout = timeout
        if client is not None and vision_module is not None:
            self._client = client
            self._vision = vision_module
            return

        try:
            from google.cloud import vision
            from google.oauth2 import service_account
        except ImportError as error:
            raise RuntimeError(
                "Google Cloud Vision dependencies are missing. Install "
                "AI-Features/requirements.txt."
            ) from error

        google_credentials = None
        if credentials is not None:
            credentials = credentials.expanduser().resolve()
            if not credentials.is_file():
                raise FileNotFoundError(
                    f"Google service-account JSON was not found: {credentials}"
                )
            google_credentials = service_account.Credentials.from_service_account_file(
                str(credentials)
            )
        self._vision = vision
        self._client = vision.ImageAnnotatorClient(credentials=google_credentials)

    @staticmethod
    def _encode_crop(crop: np.ndarray, enhanced: bool) -> bytes:
        prepared = prepare_plate_crop(crop, enhanced=enhanced)
        encoded, payload = cv2.imencode(
            ".jpg", prepared, [cv2.IMWRITE_JPEG_QUALITY, 96]
        )
        if not encoded:
            raise ValueError(
                "Could not encode the detected plate crop for Google Cloud Vision"
            )
        return payload.tobytes()

    def recognize_batch(
        self, plate_crops: list[np.ndarray], enhanced: bool = True
    ) -> list[tuple[str, float]]:
        """Recognize all crops using bounded batches to reduce network round-trips."""
        results: list[tuple[str, float]] = []
        feature = self._vision.Feature(
            type_=self._vision.Feature.Type.DOCUMENT_TEXT_DETECTION
        )
        image_context = self._vision.ImageContext(language_hints=["en"])
        for start in range(0, len(plate_crops), GOOGLE_BATCH_LIMIT):
            batch = plate_crops[start : start + GOOGLE_BATCH_LIMIT]
            requests = [
                self._vision.AnnotateImageRequest(
                    image=self._vision.Image(content=self._encode_crop(crop, enhanced)),
                    features=[feature],
                    image_context=image_context,
                )
                for crop in batch
            ]
            response = self._client.batch_annotate_images(
                requests=requests,
                timeout=self.timeout,
            )
            responses = list(getattr(response, "responses", ()))
            if len(responses) != len(batch):
                raise RuntimeError(
                    "Google Cloud Vision returned a different number of OCR responses than requests"
                )
            results.extend(_cloud_vision_result(item) for item in responses)
        return results

    def recognize(
        self, plate_bgr: np.ndarray, enhanced: bool = True
    ) -> tuple[str, float]:
        return self.recognize_batch([plate_bgr], enhanced=enhanced)[0]


class PlateCropper:
    """Yield plate boxes from a fixed ROI or an optional plate-specific YOLO model."""

    def __init__(
        self,
        detector_weights: Path | None,
        roi: list[int] | None,
        confidence: float,
        padding: float,
        minimum_size: tuple[int, int],
    ) -> None:
        self.roi = tuple(roi) if roi else None
        self.confidence = confidence
        self.padding = padding
        self.minimum_width, self.minimum_height = minimum_size
        self.detector = None
        if detector_weights:
            if not detector_weights.is_file():
                raise FileNotFoundError(
                    f"Missing plate detector weights: {detector_weights}"
                )
            try:
                from ultralytics import YOLO
            except ImportError as error:
                raise RuntimeError(
                    "Install AI-Features/requirements.txt to use plate detection."
                ) from error
            self.detector = YOLO(str(detector_weights))

    def boxes(
        self, frame: np.ndarray
    ) -> list[tuple[int, int, int, int, float, int | None]]:
        height, width = frame.shape[:2]
        if self.roi:
            x1, y1, x2, y2 = self.roi
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise ValueError(
                    f"ROI {self.roi} is outside the {width}x{height} frame"
                )
            return [(x1, y1, x2, y2, 1.0, None)]
        if self.detector is None:
            return [(0, 0, width, height, 1.0, None)]
        result = self.detector.predict(frame, conf=self.confidence, verbose=False)[0]
        if result.boxes is None:
            return []
        coords = result.boxes.xyxy.cpu().numpy().astype(int)
        scores = result.boxes.conf.cpu().numpy()
        track_ids: list[int | None]
        if result.boxes.id is None:
            track_ids = [None] * len(coords)
        else:
            track_ids = [int(value) for value in result.boxes.id.cpu().numpy()]

        boxes: list[tuple[int, int, int, int, float, int | None]] = []
        for box, score, track_id in zip(coords, scores, track_ids):
            x1, y1, x2, y2 = box.tolist()
            plate_width, plate_height = x2 - x1, y2 - y1
            if plate_width < self.minimum_width or plate_height < self.minimum_height:
                continue
            pad_x = max(2, round(plate_width * self.padding)) if self.padding else 0
            pad_y = max(2, round(plate_height * self.padding)) if self.padding else 0
            boxes.append(
                (
                    max(0, x1 - pad_x),
                    max(0, y1 - pad_y),
                    min(width, x2 + pad_x),
                    min(height, y2 + pad_y),
                    float(score),
                    track_id,
                )
            )
        return boxes


class PlateBoxTracker:
    """Assign short-lived IDs using box overlap, without optional tracker packages."""

    def __init__(self, minimum_iou: float = 0.1, maximum_misses: int = 3) -> None:
        self.minimum_iou = minimum_iou
        self.maximum_misses = maximum_misses
        self.next_id = 1
        self.tracks: dict[int, tuple[tuple[int, int, int, int], int]] = {}
        self.frame_number = 0

    @staticmethod
    def _iou(
        first: tuple[int, int, int, int], second: tuple[int, int, int, int]
    ) -> float:
        x1 = max(first[0], second[0])
        y1 = max(first[1], second[1])
        x2 = min(first[2], second[2])
        y2 = min(first[3], second[3])
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
        second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
        union = first_area + second_area - intersection
        return intersection / union if union else 0.0

    def update(self, boxes: list[tuple[int, int, int, int]]) -> list[int]:
        self.frame_number += 1
        active = {
            track_id: (box, last_seen)
            for track_id, (box, last_seen) in self.tracks.items()
            if self.frame_number - last_seen <= self.maximum_misses
        }
        assigned: list[int] = []
        used_tracks: set[int] = set()
        for box in boxes:
            overlaps = [
                (self._iou(box, previous_box), track_id)
                for track_id, (previous_box, _) in active.items()
                if track_id not in used_tracks
            ]
            best_iou, track_id = max(overlaps, default=(0.0, -1))
            if best_iou < self.minimum_iou:
                track_id = self.next_id
                self.next_id += 1
            self.tracks[track_id] = (box, self.frame_number)
            used_tracks.add(track_id)
            assigned.append(track_id)
        self.tracks = {
            track_id: value
            for track_id, value in self.tracks.items()
            if self.frame_number - value[1] <= self.maximum_misses
        }
        return assigned


class PlateConsensus:
    """Stabilize OCR by confidence-weighted voting over each YOLO track."""

    def __init__(self, history_size: int = 8) -> None:
        self.history_size = history_size
        self.histories: defaultdict[int, deque[tuple[str, float]]] = defaultdict(
            lambda: deque(maxlen=self.history_size)
        )

    def update(self, track_id: int, text: str, confidence: float) -> tuple[str, float]:
        history = self.histories[track_id]
        if text:
            history.append((text, confidence))
        if not history:
            return "", 0.0

        valid_candidates = {
            candidate
            for candidate, _ in history
            if normalize_indian_plate(candidate)[1]
        }
        direct_totals: dict[str, float] = defaultdict(float)
        for candidate, candidate_confidence in history:
            direct_totals[candidate] += candidate_confidence

        totals: dict[str, float] = defaultdict(float)
        confidences: dict[str, list[float]] = defaultdict(list)
        for candidate, candidate_confidence in history:
            _, valid_format = normalize_indian_plate(candidate)
            target = candidate
            if not valid_format:
                completions = [
                    complete
                    for complete in valid_candidates
                    if len(complete) - len(candidate) in (1, 2)
                    and complete.startswith(candidate)
                ]
                if completions:
                    target = max(completions, key=lambda value: direct_totals[value])
            target_is_valid = normalize_indian_plate(target)[1]
            totals[target] += candidate_confidence * (1.2 if target_is_valid else 1.0)
            if candidate == target:
                confidences[target].append(candidate_confidence)
        winner = max(totals, key=totals.get)
        winner_confidences = confidences[winner]
        return winner, sum(winner_confidences) / len(winner_confidences)


def annotate(
    frame: np.ndarray,
    box: tuple[int, int, int, int],
    text: str,
    ocr_confidence: float,
    detection_confidence: float,
) -> None:
    """Draw a visible detector box and both detector/OCR confidence values."""
    x1, y1, x2, y2 = box
    color = (0, 220, 0) if text else (0, 165, 255)
    label = f"PLATE {detection_confidence:.2f} | OCR: {text or 'UNREADABLE'} {ocr_confidence:.2f}"
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thickness, padding = 0.65, 2, 6
    (text_width, text_height), baseline = cv2.getTextSize(label, font, scale, thickness)
    label_height = text_height + baseline + padding * 2
    if y1 >= label_height:
        label_top, label_bottom = y1 - label_height, y1
        text_y = y1 - baseline - padding
    else:
        label_top = y1
        label_bottom = min(frame.shape[0] - 1, y1 + label_height)
        text_y = min(frame.shape[0] - baseline - 1, y1 + text_height + padding)
    label_right = min(frame.shape[1] - 1, x1 + text_width + padding * 2)

    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
    cv2.rectangle(frame, (x1, label_top), (label_right, label_bottom), color, -1)
    cv2.putText(
        frame,
        label,
        (x1 + padding, text_y),
        font,
        scale,
        (15, 15, 15),
        thickness,
        cv2.LINE_AA,
    )


def recognize_frame(
    frame: np.ndarray,
    ocr: GoogleCloudVisionOCR,
    cropper: PlateCropper,
    minimum_ocr_confidence: float,
    enhanced_ocr: bool = True,
    box_tracker: PlateBoxTracker | None = None,
    consensus: PlateConsensus | None = None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    annotated = frame.copy()
    readings: list[dict[str, Any]] = []
    detected_boxes = cropper.boxes(frame)
    if box_tracker is not None:
        track_ids = box_tracker.update([box[:4] for box in detected_boxes])
        detected_boxes = [
            (*box[:5], track_id) for box, track_id in zip(detected_boxes, track_ids)
        ]
    valid_detections: list[tuple[int, int, int, int, float, int | None]] = []
    crops: list[np.ndarray] = []
    for detection in detected_boxes:
        x1, y1, x2, y2, _detection_confidence, _track_id = detection
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        valid_detections.append(detection)
        crops.append(crop)
    recognized = ocr.recognize_batch(crops, enhanced=enhanced_ocr) if crops else []
    for detection, (text, ocr_confidence) in zip(valid_detections, recognized):
        x1, y1, x2, y2, detection_confidence, track_id = detection
        if ocr_confidence < minimum_ocr_confidence:
            text = ""
        raw_text = text
        consensus_confidence = ocr_confidence
        if consensus is not None and track_id is not None:
            text, consensus_confidence = consensus.update(
                track_id, text, ocr_confidence
            )
        annotate(
            annotated,
            (x1, y1, x2, y2),
            text,
            consensus_confidence,
            detection_confidence,
        )
        reading: dict[str, Any] = {
            "plate": text,
            "ocr_confidence": round(consensus_confidence, 4),
            "detection_confidence": round(detection_confidence, 4),
            "box": [x1, y1, x2, y2],
        }
        if track_id is not None:
            reading["track_id"] = track_id
        if raw_text != text:
            reading["raw_plate"] = raw_text
        readings.append(reading)
    return annotated, readings


def image_paths(source: Path) -> list[Path]:
    if source.is_file() and source.suffix.lower() in IMAGE_EXTENSIONS:
        return [source]
    if source.is_dir():
        return sorted(
            path for path in source.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS
        )
    return []


def process_images(
    args: argparse.Namespace, ocr: GoogleCloudVisionOCR, cropper: PlateCropper
) -> list[dict[str, Any]]:
    paths = image_paths(args.source)
    if not paths:
        raise ValueError(f"No supported images found at {args.source}")
    output_dir = Path(args.output) if args.output else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    try:
        for path in paths:
            frame = cv2.imread(str(path))
            if frame is None:
                print(f"Skipping unreadable image: {path}", file=sys.stderr)
                continue
            rendered, readings = recognize_frame(
                frame,
                ocr,
                cropper,
                args.ocr_confidence,
                enhanced_ocr=not args.fast_ocr,
            )
            results.append({"image": path.name, "readings": readings})
            for reading in readings:
                print(
                    f"{path.name}: {reading['plate'] or 'UNREADABLE'} ({reading['ocr_confidence']:.4f})"
                )
            if output_dir:
                cv2.imwrite(str(output_dir / path.name), rendered)
            if args.show:
                cv2.imshow(f"ANPR detection - {path.name}", rendered)
                if cv2.waitKey(0) & 0xFF in (ord("q"), 27):
                    break
    finally:
        if args.show:
            cv2.destroyAllWindows()
    return results


def process_video(
    args: argparse.Namespace, ocr: GoogleCloudVisionOCR, cropper: PlateCropper
) -> list[dict[str, Any]]:
    if cropper.detector is None and cropper.roi is None:
        raise ValueError(
            "Video input requires --roi or plate-specific --detector-weights"
        )
    capture = cv2.VideoCapture(str(args.source))
    if not capture.isOpened():
        raise OSError(f"Could not open video: {args.source}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = None
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            args.output, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
        )
        if not writer.isOpened():
            capture.release()
            raise OSError(f"Could not create output video: {args.output}")

    results: list[dict[str, Any]] = []
    consensus = None if args.no_temporal_consensus else PlateConsensus()
    box_tracker = None if consensus is None else PlateBoxTracker()
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % args.frame_stride:
                if writer:
                    writer.write(frame)
                if args.show:
                    cv2.imshow("ANPR detection", frame)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                        break
                frame_index += 1
                continue
            rendered, readings = recognize_frame(
                frame,
                ocr,
                cropper,
                args.ocr_confidence,
                enhanced_ocr=not args.fast_ocr,
                box_tracker=box_tracker,
                consensus=consensus,
            )
            if readings:
                results.append(
                    {
                        "frame": frame_index,
                        "time_ms": round(frame_index / fps * 1000, 2),
                        "readings": readings,
                    }
                )
            if writer:
                writer.write(rendered)
            if args.show:
                cv2.imshow("ANPR detection", rendered)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
            frame_index += 1
    finally:
        capture.release()
        if writer:
            writer.release()
        if args.show:
            cv2.destroyAllWindows()
    return results


def publish_investigation_events(
    args: argparse.Namespace, results: list[dict[str, Any]]
) -> int:
    """Publish one best consensus reading per track to the shared SIE event endpoint."""
    if not args.publish_api:
        return 0
    if not args.camera_id:
        raise ValueError("--camera-id is required with --publish-api")
    observed_start = (
        datetime.fromisoformat(args.observed_start.replace("Z", "+00:00"))
        if args.observed_start
        else datetime.now(UTC)
    )
    if observed_start.tzinfo is None:
        observed_start = observed_start.replace(tzinfo=UTC)
    best: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for group_index, group in enumerate(results):
        for reading_index, reading in enumerate(group.get("readings", [])):
            plate = str(reading.get("plate") or "").strip()
            if not plate:
                continue
            track_id = reading.get("track_id")
            group_identity = group.get("image", group.get("frame", group_index))
            key = (
                f"track:{track_id}"
                if track_id is not None
                else f"item:{group_identity}:{reading_index}"
            )
            previous = best.get(key)
            if previous is None or float(reading.get("ocr_confidence", 0)) > float(
                previous[1].get("ocr_confidence", 0)
            ):
                best[key] = (group, reading)

    endpoint = args.publish_api.rstrip("/") + "/api/v1/investigations/events"
    version = model_version(args.detector_weights)
    published = 0
    for key, (group, reading) in best.items():
        stable = f"{args.source.resolve()}|{args.camera_id}|{key}|{reading['plate']}"
        source_event_id = (
            "anpr-cli-" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:32]
        )
        observed_at = observed_start + timedelta(
            milliseconds=float(group.get("time_ms", 0))
        )
        payload = {
            "source_event_id": source_event_id,
            "camera_id": args.camera_id,
            "observed_at": observed_at.astimezone(UTC).isoformat(),
            "plate_text": reading["plate"],
            "plate_confidence": reading["ocr_confidence"],
            "vehicle_attributes": {
                "track_id": reading.get("track_id"),
                "detector_confidence": reading.get("detection_confidence"),
            },
            "evidence_reference": f"file-evidence:{args.source.name}",
            "model_version": version,
            "source": "anpr_video_detect",
        }
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Actor-ID": args.actor_id,
                "X-Actor-Role": "analytics",
            },
            method="POST",
        )
        with urlopen(request, timeout=args.publish_timeout) as response:
            if response.status not in {200, 202}:
                raise RuntimeError(
                    f"Investigation API rejected {source_event_id}: HTTP {response.status}"
                )
        published += 1
    return published


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source", type=Path, required=True, help="Plate image, image folder, or video"
    )
    default_credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    parser.add_argument(
        "--google-credentials",
        type=Path,
        default=Path(default_credentials) if default_credentials else None,
        help=(
            "Service-account JSON path. If omitted, Google Application Default "
            "Credentials are used."
        ),
    )
    parser.add_argument(
        "--google-timeout",
        type=float,
        default=8.0,
        help="Cloud Vision request timeout in seconds",
    )
    parser.add_argument(
        "--detector-weights",
        type=Path,
        default=registered_detector(),
        help="Plate-specific Ultralytics YOLO checkpoint",
    )
    parser.add_argument(
        "--no-detector",
        dest="detector_weights",
        action="store_const",
        const=None,
        help="Treat each input image as an already-cropped plate",
    )
    parser.add_argument("--detector-confidence", type=float, default=0.4)
    parser.add_argument("--ocr-confidence", type=float, default=0.35)
    parser.add_argument(
        "--crop-padding",
        type=float,
        default=0.06,
        help="Optional fractional padding around each detector box",
    )
    parser.add_argument("--minimum-plate-width", type=int, default=24)
    parser.add_argument("--minimum-plate-height", type=int, default=10)
    parser.add_argument(
        "--fast-ocr",
        action="store_true",
        help="Skip local crop contrast enhancement before Cloud Vision OCR",
    )
    parser.add_argument(
        "--no-temporal-consensus",
        action="store_true",
        help="Disable per-vehicle OCR voting in video",
    )
    parser.add_argument("--roi", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
    parser.add_argument(
        "--frame-stride", type=int, default=5, help="OCR every Nth video frame"
    )
    parser.add_argument(
        "--output", help="Annotated output directory (images) or MP4 path (video)"
    )
    parser.add_argument("--json", type=Path, help="Optional JSON results path")
    parser.add_argument(
        "--publish-api", help="Drishti API origin, for example http://127.0.0.1:8000"
    )
    parser.add_argument(
        "--camera-id", help="Registered camera UUID used when publishing ANPR events"
    )
    parser.add_argument(
        "--actor-id",
        default="anpr-edge-worker",
        help="Audited analytics publisher identity",
    )
    parser.add_argument(
        "--observed-start", help="ISO-8601 timestamp for frame zero; defaults to now"
    )
    parser.add_argument("--publish-timeout", type=float, default=5.0)
    parser.add_argument(
        "--show",
        dest="show",
        action="store_true",
        help="Show annotated preview (default)",
    )
    parser.add_argument(
        "--no-show",
        dest="show",
        action="store_false",
        help="Disable preview for headless runs",
    )
    parser.set_defaults(show=True)
    args = parser.parse_args()
    if args.frame_stride < 1:
        parser.error("--frame-stride must be at least 1")
    if args.google_timeout <= 0:
        parser.error("--google-timeout must be positive")
    if not 0.0 <= args.crop_padding <= 0.5:
        parser.error("--crop-padding must be between 0 and 0.5")
    if args.minimum_plate_width < 1 or args.minimum_plate_height < 1:
        parser.error("minimum plate dimensions must be positive")
    if args.publish_api and not args.camera_id:
        parser.error("--camera-id is required with --publish-api")
    return args


def main() -> None:
    args = parse_args()
    cropper = PlateCropper(
        args.detector_weights,
        args.roi,
        args.detector_confidence,
        args.crop_padding,
        (args.minimum_plate_width, args.minimum_plate_height),
    )
    ocr = GoogleCloudVisionOCR(
        credentials=args.google_credentials,
        timeout=args.google_timeout,
    )
    if args.source.suffix.lower() in VIDEO_EXTENSIONS:
        results = process_video(args, ocr, cropper)
    else:
        results = process_images(args, ocr, cropper)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    if args.publish_api:
        published = publish_investigation_events(args, results)
        print(
            f"Published {published} deduplicated ANPR event(s) to the investigation engine"
        )


if __name__ == "__main__":
    main()
