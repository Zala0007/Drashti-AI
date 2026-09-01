from __future__ import annotations

import base64
import io
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

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


def _fit_pattern(text: str, pattern: str) -> tuple[str, int] | None:
    if len(text) != len(pattern):
        return None
    corrected: list[str] = []
    edits = 0
    for character, expected in zip(text, pattern, strict=True):
        if expected == "A":
            replacement = character if character.isalpha() else ALPHA_CONFUSIONS.get(character)
        else:
            replacement = character if character.isdigit() else DIGIT_CONFUSIONS.get(character)
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


def normalize_indian_plate(raw: str) -> str:
    """Return one format-valid Indian registration without guessing arbitrary prose."""

    cleaned = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if not cleaned:
        return ""
    patterns = ["99AA9999AA"]
    patterns.extend(
        "AA" + "9" * district_digits + "A" * series_letters + "9999"
        for district_digits in (2, 1)
        for series_letters in (1, 2, 3)
    )
    candidates: list[tuple[str, int, int, int]] = []
    for pattern_index, pattern in enumerate(patterns):
        if len(cleaned) < len(pattern):
            continue
        for start in range(len(cleaned) - len(pattern) + 1):
            fitted = _fit_pattern(cleaned[start : start + len(pattern)], pattern)
            if fitted is None:
                continue
            value, edits = fitted
            if edits <= 2:
                candidates.append((value, edits, start, pattern_index))
    if not candidates:
        return ""
    return min(candidates, key=lambda item: (item[1], item[2], item[3]))[0]


def prepare_plate_crop(crop: bytes) -> bytes:
    """Upscale and enhance a tiny detector crop once for both OCR providers."""

    image = Image.open(io.BytesIO(crop)).convert("RGB")
    scale = min(4.0, max(1.0, 320.0 / image.width, 112.0 / image.height))
    if scale > 1:
        image = image.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
    image = ImageOps.autocontrast(image, cutoff=1)
    image = ImageEnhance.Contrast(image).enhance(1.35)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=130, threshold=2))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=96)
    return output.getvalue()


@dataclass(frozen=True, slots=True)
class OCRReading:
    provider: str
    text: str
    confidence: float
    raw_text: str | None = None
    processing_ms: float | None = None
    error: str | None = None

    @property
    def normalized_text(self) -> str:
        return normalize_indian_plate(self.text)


@dataclass(frozen=True, slots=True)
class OCRDecision:
    status: str
    accepted_text: str
    confidence: float
    provider: str | None
    reason: str
    needs_fallback: bool = False
    review_required: bool = False


class HybridOCRReconciler:
    """Conservative Google-primary, Groq-fallback decision policy."""

    def __init__(
        self,
        *,
        google_accept_confidence: float = 0.86,
        groq_accept_confidence: float = 0.82,
    ) -> None:
        self.google_accept_confidence = google_accept_confidence
        self.groq_accept_confidence = groq_accept_confidence

    def google_decision(self, google: OCRReading) -> OCRDecision:
        normalized = google.normalized_text
        if normalized and google.confidence >= self.google_accept_confidence:
            return OCRDecision(
                status="ACCEPTED",
                accepted_text=normalized,
                confidence=google.confidence,
                provider="google",
                reason="Google returned a high-confidence format-valid registration.",
            )
        return OCRDecision(
            status="FALLBACK_REQUIRED",
            accepted_text="",
            confidence=0.0,
            provider=None,
            reason=(
                "Google confidence was below the acceptance threshold."
                if normalized
                else "Google did not return a format-valid Indian registration."
            ),
            needs_fallback=True,
        )

    def reconcile(
        self, google: OCRReading | None, groq: OCRReading | None
    ) -> OCRDecision:
        google_text = google.normalized_text if google else ""
        groq_text = groq.normalized_text if groq else ""
        if google_text and groq_text and google_text == groq_text:
            confidence = (google.confidence + groq.confidence) / 2
            return OCRDecision(
                status="ACCEPTED",
                accepted_text=google_text,
                confidence=min(1.0, confidence),
                provider="hybrid",
                reason="Google and Groq independently returned the same normalized plate.",
            )
        if (
            not google_text
            and groq_text
            and groq
            and groq.confidence >= self.groq_accept_confidence
        ):
            return OCRDecision(
                status="ACCEPTED",
                accepted_text=groq_text,
                confidence=groq.confidence,
                provider="groq",
                reason="Groq recovered a format-valid plate after Google produced no valid read.",
            )
        if google_text and groq_text:
            return OCRDecision(
                status="REVIEW_REQUIRED",
                accepted_text="",
                confidence=0.0,
                provider=None,
                reason="Google and Groq returned different format-valid registrations.",
                review_required=True,
            )
        if google_text or groq_text:
            return OCRDecision(
                status="REVIEW_REQUIRED",
                accepted_text="",
                confidence=0.0,
                provider=None,
                reason="Only one provider produced a low-confidence registration candidate.",
                review_required=True,
            )
        return OCRDecision(
            status="REVIEW_REQUIRED",
            accepted_text="",
            confidence=0.0,
            provider=None,
            reason="Neither provider produced a format-valid registration.",
            review_required=True,
        )


class GooglePlateOCR:
    provider = "google"

    def __init__(self, timeout: float) -> None:
        try:
            from google.cloud import vision
        except ImportError as exc:
            raise RuntimeError("Google Cloud Vision dependencies are not installed") from exc
        self._vision = vision
        self._client = vision.ImageAnnotatorClient()
        self._timeout = timeout

    def recognize_batch(self, crops: list[bytes]) -> list[OCRReading]:
        if not crops:
            return []
        started = time.perf_counter()
        feature = self._vision.Feature(type_=self._vision.Feature.Type.DOCUMENT_TEXT_DETECTION)
        context = self._vision.ImageContext(language_hints=["en"])
        requests = [
            self._vision.AnnotateImageRequest(
                image=self._vision.Image(content=prepare_plate_crop(crop)),
                features=[feature],
                image_context=context,
            )
            for crop in crops
        ]
        response = self._client.batch_annotate_images(requests=requests, timeout=self._timeout)
        elapsed = (time.perf_counter() - started) * 1000 / len(crops)
        readings: list[OCRReading] = []
        for item in response.responses:
            if item.error.message:
                readings.append(
                    OCRReading(
                        provider=self.provider,
                        text="",
                        confidence=0.0,
                        processing_ms=elapsed,
                        error=item.error.message,
                    )
                )
                continue
            raw = getattr(item.full_text_annotation, "text", "") or ""
            confidences = [
                float(word.confidence or 0)
                for page in item.full_text_annotation.pages
                for block in page.blocks
                for paragraph in block.paragraphs
                for word in paragraph.words
            ]
            confidence = sum(confidences) / len(confidences) if confidences else 0.0
            readings.append(
                OCRReading(
                    provider=self.provider,
                    text=raw,
                    raw_text=raw,
                    confidence=min(1.0, max(0.0, confidence)),
                    processing_ms=elapsed,
                )
            )
        return readings

    def recognize(self, crop: bytes) -> OCRReading:
        return self.recognize_batch([crop])[0]


class GroqPlateOCR:
    provider = "groq"

    def __init__(self, *, api_key: str, model: str, timeout: float, max_retries: int) -> None:
        try:
            from groq import Groq
        except ImportError as exc:
            raise RuntimeError("The groq package is not installed") from exc
        self.model = model
        self._client = Groq(api_key=api_key, timeout=timeout, max_retries=max_retries)

    def recognize(self, crop: bytes) -> OCRReading:
        started = time.perf_counter()
        encoded = base64.b64encode(prepare_plate_crop(crop)).decode("ascii")
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict vehicle-registration OCR reader. Read only characters "
                        "visibly printed on the actual plate. Ignore reflections and shadows. "
                        "Never infer hidden characters."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Return JSON with raw_text, plate_text, and confidence from 0 to "
                                "1. Use empty strings and confidence 0 when unreadable."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
            reasoning_effort="none",
            reasoning_format="hidden",
            temperature=0,
            top_p=0.8,
            max_completion_tokens=256,
            stream=False,
        )
        content = completion.choices[0].message.content or "{}"
        parsed: dict[str, Any] = json.loads(
            re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        )
        plate_text = str(parsed.get("plate_text") or parsed.get("raw_text") or "")
        return OCRReading(
            provider=self.provider,
            text=plate_text,
            raw_text=str(parsed.get("raw_text") or plate_text),
            confidence=min(1.0, max(0.0, float(parsed.get("confidence") or 0))),
            processing_ms=(time.perf_counter() - started) * 1000,
        )
