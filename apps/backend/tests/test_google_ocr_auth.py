from unittest.mock import Mock

import pytest

from app.analytics.ocr import GooglePlateOCR

compute_engine = pytest.importorskip("google.auth.compute_engine")
vision = pytest.importorskip("google.cloud.vision")


def test_metadata_auth_uses_attached_identity_even_with_stale_json(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/missing/stale-key.json")
    client = Mock()
    monkeypatch.setattr(vision, "ImageAnnotatorClient", client)

    GooglePlateOCR(timeout=8, auth_mode="metadata")

    credentials = client.call_args.kwargs["credentials"]
    assert isinstance(credentials, compute_engine.Credentials)
    assert credentials.scopes == ["https://www.googleapis.com/auth/cloud-platform"]


def test_adc_mode_preserves_standard_google_authentication(monkeypatch):
    client = Mock()
    monkeypatch.setattr(vision, "ImageAnnotatorClient", client)
    GooglePlateOCR(timeout=8, auth_mode="adc")
    client.assert_called_once_with()


def test_unknown_auth_mode_is_rejected():
    with pytest.raises(ValueError, match="GOOGLE_OCR_AUTH_MODE"):
        GooglePlateOCR(timeout=8, auth_mode="unknown")
