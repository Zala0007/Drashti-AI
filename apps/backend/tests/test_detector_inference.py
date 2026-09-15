from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.analytics.worker import _UltralyticsDetector


@pytest.mark.parametrize("has_plate", [True, False])
def test_objects_use_sahi_and_plates_use_full_frame_yolo(has_plate: bool) -> None:
    detector = object.__new__(_UltralyticsDetector)
    detector.device = "cpu"
    detector._plate_confidence = 0.35
    detector._plate_image_size = 1280
    detector._general_sahi = object()
    detector._predict_sahi = Mock(return_value=SimpleNamespace(object_prediction_list=[
        SimpleNamespace(
            bbox=SimpleNamespace(minx=1, miny=2, maxx=150, maxy=85),
            category=SimpleNamespace(id=2, name="car"),
            score=SimpleNamespace(value=0.9),
        )
    ]))
    boxes = Mock()
    boxes.cpu.return_value = boxes
    boxes.xyxy.tolist.return_value = [[30, 45, 70, 60]] if has_plate else []
    boxes.cls.tolist.return_value = [0] if has_plate else []
    boxes.conf.tolist.return_value = [0.88765] if has_plate else []
    detector._plate_model = Mock()
    detector._plate_model.predict.return_value = [SimpleNamespace(boxes=boxes)]
    packet = SimpleNamespace(width=160, height=90, payload=bytes(160 * 90 * 3))

    [(image, detections)] = detector.predict((packet,))

    assert image.size == (160, 90)
    detector._predict_sahi.assert_called_once_with(image, detector._general_sahi)
    detector._plate_model.predict.assert_called_once_with(
        source=image, conf=0.35, imgsz=1280, device="cpu", verbose=False
    )
    assert detections[0].kind == "object"
    assert detections[0].class_name == "car"
    assert len(detections) == (2 if has_plate else 1)
    if has_plate:
        plate = detections[1]
        assert plate.kind == "plate"
        assert plate.class_name == "license_plate"
        assert (plate.x1, plate.y1, plate.x2, plate.y2) == (30, 45, 70, 60)
        assert plate.confidence == 0.8877
