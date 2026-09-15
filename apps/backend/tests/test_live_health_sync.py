from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from app.services.camera_health import CameraHealthService


def test_newest_live_session_wins_over_stopped_history():
    camera = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001", status="active", installation_metadata={}
    )
    now = datetime.now(UTC)
    metrics = SimpleNamespace(
        decoded_fps=10,
        processing_fps=8,
        latency_estimate_ms=100,
        current_frame_age_ms=100,
        reconnect_count=0,
        decoder_errors=0,
        frames_dispatched=30,
        frames_received=40,
        frames_dropped=0,
    )
    live = SimpleNamespace(
        camera=camera, created_at=now, state="streaming", metrics=metrics, last_error_code=None
    )
    stopped = SimpleNamespace(
        camera=camera,
        created_at=now - timedelta(minutes=1),
        state="stopped",
        metrics=metrics,
        last_error_code=None,
    )
    session = Mock()
    session.scalars.return_value = [camera]
    service = CameraHealthService(
        session,
        engine=Mock(list=Mock(return_value=[live, stopped])),
        actor_id="test",
        request_id=None,
    )
    service.ingest = Mock()
    service.dashboard = Mock()
    service.capture_live_snapshot(only_streams=True)
    payload = service.ingest.call_args.args[0]
    assert payload.availability == 1.0
    assert service._state(payload, camera) == "healthy"
    # A later stopped session must still be reflected as offline.
    stopped.created_at = now + timedelta(minutes=1)
    service.capture_live_snapshot(only_streams=True)
    assert service.ingest.call_args.args[0].availability == 0.0


def test_background_sync_does_not_invent_heartbeats_or_revive_retired_cameras():
    retired = SimpleNamespace(id="retired", status="retired")
    idle = SimpleNamespace(id="idle", status="active")
    session = Mock()
    session.scalars.return_value = [retired, idle]
    engine = Mock(
        list=Mock(return_value=[SimpleNamespace(camera=retired, created_at=datetime.now(UTC))])
    )
    service = CameraHealthService(session, engine=engine, actor_id="test", request_id=None)
    service.ingest = Mock()
    service.dashboard = Mock()
    service.capture_live_snapshot(only_streams=True)
    service.ingest.assert_not_called()
