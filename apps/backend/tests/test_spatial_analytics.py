from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from app.analytics.spatial import SpatialAnalytics, SpatialRule
from app.analytics.worker import AnalyticsDetection


def rule(feature, points=()):
    return SpatialRule(feature=feature, points=[{"x": x, "y": y} for x, y in points])


def process(store, y, frame, camera="one", stream="stream-one"):
    packet = SimpleNamespace(
        camera_id=camera,
        stream_id=stream,
        frame_number=frame,
        capture_timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=frame),
    )
    store.process(
        packet,
        Image.new("RGB", (200, 200)),
        [
            AnalyticsDetection("object", 0, "person", 0.9, 80, y - 50, 120, y, track_id=1),
        ],
    )


def test_border_crossing_is_confirmed_finite_and_camera_scoped(tmp_path):
    store = SpatialAnalytics(str(tmp_path / "spatial.db"))
    store.save("one", rule("border_line", [(0.2, 0.5), (0.8, 0.5)]))
    for frame, y in enumerate([80, 110, 120, 125], 1):
        process(store, y, frame)
        process(store, y, frame, camera="two")
    events = store.read("one")["events"]
    assert len(events) == 1
    assert events[0]["direction"] == "A_TO_B"
    assert store.read("two")["events"] == []
    # A new stream must not inherit an earlier position or crossing.
    process(store, 80, 1, stream="replacement")
    assert len(store.read("one")["events"]) == 1
    store.close()


def test_fence_entry_does_not_repeat_and_rules_survive_restart(tmp_path):
    database = str(tmp_path / "spatial.db")
    store = SpatialAnalytics(database)
    store.save("one", rule("virtual_fence", [(0.2, 0.5), (0.8, 0.5), (0.8, 0.9), (0.2, 0.9)]))
    for frame, y in enumerate([80, 110, 120, 125], 1):
        process(store, y, frame)
    assert len(store.read("one")["events"]) == 1
    assert store.read("one")["live"]["inside"] == 1
    store.close()
    reopened = SpatialAnalytics(database)
    assert reopened.read("one")["rules"][0]["enabled"] is True
    assert len(reopened.read("one")["events"]) == 1
    reopened.close()


def test_switching_module_preserves_other_camera_and_disabling_stops_events(tmp_path):
    store = SpatialAnalytics(str(tmp_path / "spatial.db"))
    border = rule("border_line", [(0.2, 0.5), (0.8, 0.5)])
    store.save("one", border)
    store.save("two", border)
    store.save("one", rule("object_path"))
    assert [r["feature"] for r in store.read("one")["rules"] if r["enabled"]] == ["object_path"]
    assert store.read("two")["rules"][0]["enabled"]
    process(store, 70, 1)
    process(store, 80, 2)
    assert len(store.read("one")["live"]["paths"][0]["points"]) == 2
    store.save("one", SpatialRule(feature="object_path", enabled=False))
    process(store, 100, 3)
    assert store.read("one")["live"] is None
    store.close()


@pytest.mark.parametrize(
    "feature,points",
    [
        ("border_line", [(0, 0), (0, 0)]),
        ("border_line", [(0, 0)]),
        ("virtual_fence", [(0, 0), (0.5, 0.5), (1, 1)]),
        ("night_movement", [(0, 0), (1, 1)]),
        ("virtual_fence", [(0, 0), (1.2, 0), (1, 1)]),
    ],
)
def test_invalid_drawings_are_rejected(feature, points):
    with pytest.raises(ValidationError):
        rule(feature, points)


def test_night_motion_warms_up_without_false_event(tmp_path):
    store = SpatialAnalytics(str(tmp_path / "spatial.db"))
    store.save("one", rule("night_movement", [(0, 0), (1, 0), (1, 1), (0, 1)]))
    for frame in range(1, 8):
        process(store, 80, frame)
    assert store.read("one")["events"] == []
    assert store.read("one")["live"]["warming_up"] is False
    store.close()
