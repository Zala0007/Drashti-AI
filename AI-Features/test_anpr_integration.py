from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np


def load_script(name: str) -> Any:
    path = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_registered_detector_is_checksum_verified() -> None:
    anpr = load_script("anpr_video_detect")
    detector = anpr.registered_detector()
    registry = json.loads(anpr.MODEL_REGISTRY.read_text(encoding="utf-8"))
    assert detector.name == registry["active_detector"]["file"]
    assert anpr.file_sha256(detector) == registry["active_detector"]["sha256"]


def test_event_publisher_deduplicates_track_and_attributes_exact_models(
    tmp_path: Path, monkeypatch: Any
) -> None:
    anpr = load_script("anpr_video_detect")
    detector = tmp_path / "detector.pt"
    source = tmp_path / "traffic.mp4"
    detector.write_bytes(b"detector-checkpoint")
    source.write_bytes(b"video")
    requests: list[Any] = []

    class Response:
        status = 202

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

    def fake_urlopen(request: Any, timeout: float) -> Response:
        assert timeout == 3
        requests.append(request)
        return Response()

    monkeypatch.setattr(anpr, "urlopen", fake_urlopen)
    args = argparse.Namespace(
        publish_api="http://127.0.0.1:8000",
        camera_id="ca0557ad-1cce-46ba-96f6-448d4db7aebf",
        observed_start="2026-08-30T12:00:00Z",
        source=source,
        actor_id="edge-worker-test",
        publish_timeout=3,
        detector_weights=detector,
    )
    results = [
        {
            "frame": 1,
            "time_ms": 100,
            "readings": [
                {
                    "track_id": 7,
                    "plate": "GJ01A81234",
                    "ocr_confidence": 0.72,
                    "detection_confidence": 0.91,
                }
            ],
        },
        {
            "frame": 2,
            "time_ms": 200,
            "readings": [
                {
                    "track_id": 7,
                    "plate": "GJ01AB1234",
                    "ocr_confidence": 0.96,
                    "detection_confidence": 0.94,
                }
            ],
        },
    ]

    assert anpr.publish_investigation_events(args, results) == 1
    assert len(requests) == 1
    payload = json.loads(requests[0].data)
    assert payload["plate_text"] == "GJ01AB1234"
    assert payload["model_version"].startswith("detector=detector:")
    assert (
        ";ocr=google-cloud-vision:document-text-detection-v1"
        in payload["model_version"]
    )
    assert requests[0].headers["X-actor-role"] == "analytics"


def test_cloud_vision_result_normalizes_plate_and_weights_confidence() -> None:
    anpr = load_script("anpr_video_detect")
    first_word = SimpleNamespace(
        confidence=0.9,
        symbols=[SimpleNamespace(text=value) for value in "GJ01"],
    )
    second_word = SimpleNamespace(
        confidence=0.8,
        symbols=[SimpleNamespace(text=value) for value in "AB1234"],
    )
    response = SimpleNamespace(
        error=SimpleNamespace(message=""),
        full_text_annotation=SimpleNamespace(
            text="GJ 01 AB 1234\n",
            pages=[
                SimpleNamespace(
                    blocks=[
                        SimpleNamespace(
                            paragraphs=[
                                SimpleNamespace(words=[first_word, second_word])
                            ]
                        )
                    ]
                )
            ],
        ),
    )

    plate, confidence = anpr._cloud_vision_result(response)

    assert plate == "GJ01AB1234"
    assert abs(confidence - 0.84) < 1e-9


def test_plate_normalization_recovers_registration_from_repeated_cloud_text() -> None:
    anpr = load_script("anpr_video_detect")

    assert anpr.normalize_indian_plate("FAP09CP5546 AP09CP5546") == (
        "AP09CP5546",
        True,
    )


def test_cloud_vision_result_rejects_unstructured_text() -> None:
    anpr = load_script("anpr_video_detect")
    response = SimpleNamespace(
        error=SimpleNamespace(message=""),
        full_text_annotation=SimpleNamespace(text="NOT A REGISTRATION", pages=[]),
    )

    assert anpr._cloud_vision_result(response) == ("", 0.0)


def test_cloud_vision_ocr_batches_encoded_plate_crops() -> None:
    anpr = load_script("anpr_video_detect")
    annotation = SimpleNamespace(text="GJ01AB1234", pages=[])
    api_response = SimpleNamespace(
        responses=[
            SimpleNamespace(
                error=SimpleNamespace(message=""),
                full_text_annotation=annotation,
            )
        ]
    )

    class FakeClient:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        def batch_annotate_images(self, requests: list[Any], timeout: float) -> Any:
            assert timeout == 4.0
            self.requests.extend(requests)
            return api_response

    class FakeVision:
        class Feature:
            class Type:
                DOCUMENT_TEXT_DETECTION = "document-text"

            def __init__(self, type_: str) -> None:
                self.type_ = type_

        Image = SimpleNamespace
        ImageContext = SimpleNamespace
        AnnotateImageRequest = SimpleNamespace

    client = FakeClient()
    ocr = anpr.GoogleCloudVisionOCR(
        client=client,
        vision_module=FakeVision,
        timeout=4.0,
    )

    results = ocr.recognize_batch([np.zeros((24, 80, 3), dtype=np.uint8)])

    assert results == [("GJ01AB1234", 0.0)]
    assert len(client.requests) == 1
    assert client.requests[0].image.content.startswith(b"\xff\xd8")


def test_ocr_evaluator_uses_exact_normalized_plate_accuracy() -> None:
    evaluator = load_script("evaluate_anpr_results")
    predictions = evaluator.best_predictions(
        [
            {
                "image": "plate-1.jpg",
                "readings": [
                    {"plate": "GJ 01 AB 1234", "ocr_confidence": 0.97},
                    {"plate": "GJ01A81234", "ocr_confidence": 0.70},
                ],
            }
        ]
    )
    assert predictions == {"plate-1.jpg": "GJ01AB1234"}
    assert evaluator.edit_distance("GJ01AB1234", "GJ01A81234") == 1
