"""Persist live stream telemetry so registry filters and GIS share camera health."""

import logging
import threading

from app.services.camera_health import CameraHealthService

logger = logging.getLogger(__name__)


class LiveHealthSync:
    def __init__(self, engine, session_factory, interval=10):
        self.engine = engine
        self.session_factory = session_factory
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None

    def startup(self):
        self.thread = threading.Thread(target=self._run, name="live-health-sync", daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                if self.engine.list():
                    with self.session_factory() as session:
                        CameraHealthService(
                            session,
                            engine=self.engine,
                            actor_id="live-health-sync",
                            request_id=None,
                        ).capture_live_snapshot(only_streams=True)
            except Exception:
                logger.exception("Live health synchronization failed; retrying next interval")
            self.stop_event.wait(self.interval)

    def shutdown(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)
