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
