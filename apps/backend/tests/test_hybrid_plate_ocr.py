from __future__ import annotations

import pytest

from app.analytics.ocr import HybridOCRReconciler, OCRReading, normalize_indian_plate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("gj-01 ab 1234", "GJ01AB1234"),
        ("APO9 CP 5546", "AP09CP5546"),
        ("APO9 CP 5546 / APU9CP5546", "AP09CP5546"),
        ("DL 1 C AA 1234", "DL1CAA1234"),
        ("22 bh 1234 aa", "22BH1234AA"),
        ("22 xx 1234 aa", ""),
        ("no plate visible", ""),
    ],
)
def test_indian_plate_normalization_is_format_aware(raw: str, expected: str) -> None:
    assert normalize_indian_plate(raw) == expected


def test_high_confidence_valid_google_read_skips_paid_fallback() -> None:
    reconciler = HybridOCRReconciler()

    result = reconciler.google_decision(
        OCRReading(provider="google", text="GJ 01 AB 1234", confidence=0.94)
    )

    assert result.status == "ACCEPTED"
    assert result.accepted_text == "GJ01AB1234"
    assert result.provider == "google"
    assert result.needs_fallback is False


@pytest.mark.parametrize(
    "reading",
    [
        OCRReading(provider="google", text="GJ01AB1234", confidence=0.64),
        OCRReading(provider="google", text="unreadable", confidence=0.99),
    ],
)
def test_low_confidence_or_invalid_google_read_requests_fallback(reading: OCRReading) -> None:
    result = HybridOCRReconciler().google_decision(reading)

    assert result.status == "FALLBACK_REQUIRED"
    assert result.accepted_text == ""
    assert result.needs_fallback is True


def test_google_and_groq_agreement_accepts_normalized_plate() -> None:
    reconciler = HybridOCRReconciler()
    google = OCRReading(provider="google", text="APO9 CP 5546", confidence=0.70)
    groq = OCRReading(provider="groq", text="AP09CP5546", confidence=0.93)

    result = reconciler.reconcile(google, groq)

    assert result.status == "ACCEPTED"
    assert result.accepted_text == "AP09CP5546"
    assert result.provider == "hybrid"
    assert result.needs_fallback is False


def test_material_provider_disagreement_requires_review_and_cannot_hit_watchlist() -> None:
    reconciler = HybridOCRReconciler()
    google = OCRReading(provider="google", text="GJ01AB1234", confidence=0.72)
    groq = OCRReading(provider="groq", text="GJ01AB1284", confidence=0.96)

    result = reconciler.reconcile(google, groq)

    assert result.status == "REVIEW_REQUIRED"
    # An ambiguous OCR reading must not be accepted into investigation/watchlist matching.
    assert result.accepted_text == ""
    assert result.needs_fallback is False


def test_valid_groq_only_result_can_recover_a_failed_google_request() -> None:
    result = HybridOCRReconciler().reconcile(
        None,
        OCRReading(provider="groq", text="MH 12 DE 1433", confidence=0.91),
    )

    assert result.status == "ACCEPTED"
    assert result.accepted_text == "MH12DE1433"
    assert result.provider == "groq"
    assert result.needs_fallback is False


def test_groq_plate_ocr_switches_key_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock
    from app.analytics.ocr import GroqPlateOCR

    # Mock groq module
    call_log = []

    class MockCompletion:
        def __init__(self, key: str):
            self.key = key

        def create(self, **kwargs):
            call_log.append(self.key)
            if self.key == "key-1":
                raise RuntimeError("Rate limit reached: 429 Too Many Requests")
            msg = MagicMock()
            msg.content = '{"raw_text": "GJ01AB1234", "plate_text": "GJ01AB1234", "confidence": 0.95}'
            choice = MagicMock()
            choice.message = msg
            res = MagicMock()
            res.choices = [choice]
            return res

    class MockGroq:
        def __init__(self, api_key: str, **kwargs):
            self.api_key = api_key
            self.chat = MagicMock()
            self.chat.completions = MockCompletion(api_key)

    monkeypatch.setattr("groq.Groq", MockGroq)

    ocr = GroqPlateOCR(
        api_keys=("key-1", "key-2", "key-3"),
        model="qwen/qwen3.6-27b",
        timeout=10.0,
        max_retries=1,
    )

    dummy_jpeg = b"\xff\xd8\xff\xd9"
    # Create valid JPEG image bytes
    from PIL import Image
    import io
    img = Image.new("RGB", (100, 50), color="white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    crop_bytes = buf.getvalue()

    reading = ocr.recognize(crop_bytes)
    assert reading.text == "GJ01AB1234"
    assert reading.confidence == 0.95
    assert call_log == ["key-1", "key-2"]

