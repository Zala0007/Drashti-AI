"""Check local AI setup; --live sends synthetic test images to the configured providers.

Run from the repository root with the project's virtual-environment Python.
No stored footage, evidence database or credential contents are uploaded or printed.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Check provider APIs using synthetic images only"
    )
    parser.add_argument(
        "--provider", choices=("all", "google_ocr", "groq_ocr", "groq_vision"), default="all"
    )
    args = parser.parse_args()
    settings = get_settings()
    modules = {}
    for name in ("google.cloud.vision", "groq", "ultralytics", "sahi", "cv2"):
        try:
            modules[name] = importlib.util.find_spec(name) is not None
        except ModuleNotFoundError:
            modules[name] = False
    keys = settings.groq_api_keys or ((settings.groq_api_key,) if settings.groq_api_key else ())
    credentials = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    checks = {
        "dependencies": modules,
        "google_credentials_file_exists": bool(credentials and Path(credentials).is_file()),
        "google_auth_mode": settings.google_ocr_auth_mode,
        "groq_keys_configured": len(keys),
        "groq_model": settings.groq_vision_model,
        "general_model_exists": Path(settings.live_analytics_general_model).is_file(),
        "plate_model_exists": Path(settings.live_analytics_plate_model).is_file(),
        "ocr_enabled": settings.live_analytics_ocr_enabled,
        "groq_ocr_enabled": settings.live_analytics_groq_ocr_enabled,
        "visual_intelligence_enabled": settings.visual_intelligence_enabled,
        "auto_analyze": settings.visual_intelligence_auto_analyze,
    }
    print(json.dumps(checks, indent=2), flush=True)
    if not args.live:
        return 0 if all(modules.values()) else 1

    from PIL import Image, ImageDraw, ImageFont

    from app.analytics.ocr import GooglePlateOCR, GroqPlateOCR
    from app.services.visual_intelligence import GroqVisionProvider

    plate_image = Image.new("RGB", (640, 160), "white")
    plate_draw = ImageDraw.Draw(plate_image)
    font_path = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf"
    font = (
        ImageFont.truetype(str(font_path), 70)
        if font_path.is_file()
        else ImageFont.load_default(size=70)
    )
    plate_draw.rectangle((5, 5, 634, 154), outline="black", width=4)
    plate_draw.text((40, 35), "GJ01AB1234", fill="black", font=font)
    vehicle_image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(vehicle_image)
    draw.rectangle((100, 150, 540, 260), fill="red")
    draw.polygon([(190, 150), (240, 80), (420, 80), (470, 150)], fill="red")
    draw.polygon([(220, 145), (250, 95), (320, 95), (320, 145)], fill="lightblue")
    draw.polygon([(335, 95), (410, 95), (445, 145), (335, 145)], fill="lightblue")
    for x in (170, 440):
        draw.ellipse((x - 40, 225, x + 40, 305), fill="black")

    def encode(image):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        return buffer.getvalue()

    plate, vehicle = encode(plate_image), encode(vehicle_image)
    print(
        json.dumps(
            {"live_test_input": "synthetic plate and illustrated vehicle; no stored evidence"}
        ),
        flush=True,
    )
    groq_options = dict(api_keys=keys, model=settings.groq_vision_model, timeout=15, max_retries=0)

    def google_check():
        reading = GooglePlateOCR(timeout=10, auth_mode=settings.google_ocr_auth_mode).recognize(
            plate
        )
        return {
            "ok": not bool(reading.error),
            "plate_detected": bool(reading.normalized_text),
            "expected_plate_matched": reading.normalized_text == "GJ01AB1234",
            "confidence": reading.confidence,
        }

    def groq_ocr_check():
        reading = GroqPlateOCR(**groq_options).recognize(plate)
        return {
            "ok": not bool(reading.error),
            "plate_detected": bool(reading.normalized_text),
            "expected_plate_matched": reading.normalized_text == "GJ01AB1234",
            "confidence": reading.confidence,
        }

    def groq_vision_check():
        profile = GroqVisionProvider(**groq_options).analyze_vehicle(vehicle)
        return {"ok": True, "vehicle_present": profile.vehicle_present, "profile_validated": True}

    passed = True
    with ThreadPoolExecutor(max_workers=3) as executor:
        jobs = {
            executor.submit(fn): name
            for name, fn in (
                ("google_ocr", google_check),
                ("groq_ocr", groq_ocr_check),
                ("groq_vision", groq_vision_check),
            )
            if args.provider in ("all", name)
        }
        for future in as_completed(jobs):
            try:
                result = future.result()
            except Exception as exc:
                # Provider exception bodies may contain credentials, URLs or source imagery.
                result = {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "http_status": getattr(exc, "status_code", None),
                }
                message = str(exc).lower()
                for phrase, diagnosis in (
                    (
                        "invalid jwt signature",
                        "Google key signature is invalid; replace the revoked or incorrect key.",
                    ),
                    (
                        "invalid_grant",
                        "Google rejected the credential grant; check the key and system clock.",
                    ),
                    (
                        "invalid authentication credentials",
                        "Google rejected the configured authentication credentials.",
                    ),
                    ("tokens per day", "Groq daily token quota exhausted."),
                    ("tokens per minute", "Groq minute token limit reached; wait before retrying."),
                    ("requests per day", "Groq daily request quota exhausted."),
                    (
                        "requests per minute",
                        "Groq minute request limit reached; wait before retrying.",
                    ),
                    ("billing", "Provider billing must be enabled or repaired."),
                ):
                    if phrase in message:
                        result["diagnosis"] = diagnosis
                        break
                response = getattr(exc, "response", None)
                headers = getattr(response, "headers", {})
                if headers.get("retry-after"):
                    result["retry_after_seconds"] = headers["retry-after"]
            passed = passed and result["ok"]
            print(json.dumps({"provider": jobs[future], **result}), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
