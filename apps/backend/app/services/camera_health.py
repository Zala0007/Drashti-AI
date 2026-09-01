from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import (
    AuditLog,
    Camera,
    CameraHealthAggregate,
    HealthIncident,
    MaintenanceFinding,
)
from app.schemas.advanced import (
    HealthAggregateCreate,
    HealthAggregateRead,
    HealthDashboard,
    HealthHistoryRead,
    HealthIncidentRead,
    MaintenanceRead,
)
from app.services.advanced_common import camera_read
from app.stream_engine import StreamEngine


class CameraHealthService:
    def __init__(
        self,
        session: Session,
        *,
        engine: StreamEngine,
        actor_id: str,
        request_id: str | None,
    ) -> None:
        self.session = session
        self.engine = engine
        self.actor_id = actor_id
        self.request_id = request_id

    def ingest(self, payload: HealthAggregateCreate) -> HealthAggregateRead:
        camera = self.session.get(Camera, str(payload.camera_id))
        if not camera:
            raise NotFoundError("camera", str(payload.camera_id))
        bucket_start = self._bucket(payload.bucket_start, payload.bucket_seconds)
        aggregate = self.session.scalar(
            select(CameraHealthAggregate).where(
                CameraHealthAggregate.camera_id == camera.id,
                CameraHealthAggregate.bucket_start == bucket_start,
                CameraHealthAggregate.bucket_seconds == payload.bucket_seconds,
            )
        )
        state = self._state(payload, camera)
        if not aggregate:
            aggregate = CameraHealthAggregate(
                camera_id=camera.id,
                bucket_start=bucket_start,
                bucket_seconds=payload.bucket_seconds,
            )
            self.session.add(aggregate)
        aggregate.health_state = state
        aggregate.availability = payload.availability
        aggregate.decoded_fps = payload.decoded_fps
        aggregate.processing_fps = payload.processing_fps
        aggregate.latency_ms = payload.latency_ms
        aggregate.frame_age_ms = payload.frame_age_ms
        aggregate.reconnect_count = payload.reconnect_count
        aggregate.decoder_errors = payload.decoder_errors
        aggregate.freeze_events = payload.freeze_events
        aggregate.authentication_failures = payload.authentication_failures
        aggregate.image_quality_state = payload.image_quality_state
        aggregate.edge_node_id = payload.edge_node_id
        aggregate.ai_worker_state = payload.ai_worker_state
        aggregate.source = payload.source
        aggregate.details = payload.details
        camera.health = {"healthy": "online", "offline": "offline", "unknown": "unknown"}.get(
            state, "degraded"
        )
        camera.last_heartbeat = datetime.now(UTC)
        camera.health_details = {
            "state": state,
            "source": payload.source,
            "bucket_start": bucket_start.isoformat(),
            "image_quality_state": payload.image_quality_state,
        }
        self.session.flush()
        self._refresh_maintenance(camera)
        self._refresh_incidents()
        self.session.commit()
        return self._aggregate_read(aggregate, camera)

    def capture_live_snapshot(self) -> HealthDashboard:
        sessions = {snapshot.camera.id: snapshot for snapshot in self.engine.list()}
        now = datetime.now(UTC)
        cameras = list(self.session.scalars(select(Camera).order_by(Camera.camera_code)))
        for camera in cameras:
            snapshot = sessions.get(camera.id)
            if snapshot:
                metrics = snapshot.metrics
                availability = (
                    1.0
                    if snapshot.state == "streaming"
                    else 0.65
                    if snapshot.state in {"connected", "degraded", "reconnecting"}
                    else 0.0
                )
                payload = HealthAggregateCreate(
                    camera_id=camera.id,
                    bucket_start=now,
                    availability=availability,
                    decoded_fps=metrics.decoded_fps,
                    processing_fps=metrics.processing_fps,
                    latency_ms=metrics.latency_estimate_ms,
                    frame_age_ms=metrics.current_frame_age_ms,
                    reconnect_count=metrics.reconnect_count,
                    decoder_errors=metrics.decoder_errors,
                    freeze_events=1 if snapshot.last_error_code == "STREAM_FROZEN" else 0,
                    authentication_failures=(
                        1 if snapshot.last_error_code and "AUTH" in snapshot.last_error_code else 0
                    ),
                    edge_node_id=str(camera.installation_metadata.get("edge_node_id") or "")
                    or None,
                    ai_worker_state="healthy" if metrics.frames_dispatched > 0 else "unknown",
                    source="p04_stream_engine",
                    details={
                        "stream_state": str(snapshot.state),
                        "last_error_code": snapshot.last_error_code,
                        "frames_received": metrics.frames_received,
                        "frames_dropped": metrics.frames_dropped,
                    },
                )
            else:
                availability = (
                    1.0 if camera.health == "online" else 0.0 if camera.health == "offline" else 0.5
                )
                payload = HealthAggregateCreate(
                    camera_id=camera.id,
                    bucket_start=now,
                    availability=availability,
                    edge_node_id=str(camera.installation_metadata.get("edge_node_id") or "")
                    or None,
                    source="registry_heartbeat",
                    details={
                        "stream_session": "not_active",
                        "registry_health": camera.health,
                        "last_heartbeat": camera.last_heartbeat.isoformat()
                        if camera.last_heartbeat
                        else None,
                    },
                )
            self.ingest(payload)
        return self.dashboard()

    def dashboard(self) -> HealthDashboard:
        cameras = list(self.session.scalars(select(Camera).order_by(Camera.camera_code)))
        latest: list[tuple[CameraHealthAggregate, Camera]] = []
        states = {
            key: 0
            for key in ("healthy", "degraded", "critical", "offline", "unknown", "maintenance")
        }
        for camera in cameras:
            aggregate = self.session.scalar(
                select(CameraHealthAggregate)
                .where(CameraHealthAggregate.camera_id == camera.id)
                .order_by(CameraHealthAggregate.bucket_start.desc())
                .limit(1)
            )
            if aggregate:
                latest.append((aggregate, camera))
                states[aggregate.health_state] = states.get(aggregate.health_state, 0) + 1
            else:
                fallback = "maintenance" if camera.status == "maintenance" else "unknown"
                states[fallback] += 1
        findings = list(
            self.session.scalars(
                select(MaintenanceFinding)
                .where(MaintenanceFinding.status == "open")
                .order_by(MaintenanceFinding.risk, MaintenanceFinding.updated_at.desc())
            )
        )
        incidents = list(
            self.session.scalars(
                select(HealthIncident)
                .where(HealthIncident.status == "open")
                .order_by(HealthIncident.severity, HealthIncident.updated_at.desc())
            )
        )
        risk = {key: 0 for key in ("high", "medium", "low")}
        for finding in findings:
            risk[finding.risk] = risk.get(finding.risk, 0) + 1
        return HealthDashboard(
            total_cameras=len(cameras),
            states=states,
            maintenance_risk=risk,
            latest=[self._aggregate_read(item, camera) for item, camera in latest],
            findings=[self._maintenance_read(item) for item in findings],
            incidents=[HealthIncidentRead.model_validate(item) for item in incidents],
            telemetry_basis=(
                "Latest persisted 5-minute aggregates from the P04 stream engine, edge "
                "aggregators, or registry heartbeats. No random health values are generated."
            ),
        )

    def history(self, camera_id: str, *, limit: int = 96) -> HealthHistoryRead:
        camera = self.session.get(Camera, camera_id)
        if not camera:
            raise NotFoundError("camera", camera_id)
        items = list(
            self.session.scalars(
                select(CameraHealthAggregate)
                .where(CameraHealthAggregate.camera_id == camera.id)
                .order_by(CameraHealthAggregate.bucket_start.desc())
                .limit(limit)
            )
        )
        return HealthHistoryRead(
            camera=camera_read(camera),
            items=[self._aggregate_read(item, camera) for item in items],
            telemetry_basis=(
                "Persisted aggregate history; raw frames and credentials are never returned."
            ),
        )

    def _refresh_maintenance(self, camera: Camera) -> None:
        samples = list(
            self.session.scalars(
                select(CameraHealthAggregate)
                .where(
                    CameraHealthAggregate.camera_id == camera.id,
                    CameraHealthAggregate.bucket_start >= datetime.now(UTC) - timedelta(days=7),
                )
                .order_by(CameraHealthAggregate.bucket_start)
            )
        )
        if len(samples) < 2:
            return
        indicators: list[str] = []
        reconnects = [item.reconnect_count for item in samples]
        fps = [item.decoded_fps for item in samples if item.decoded_fps is not None]
        latency = [item.latency_ms for item in samples if item.latency_ms is not None]
        outages = sum(item.availability < 0.5 for item in samples)
        if reconnects[-1] > reconnects[0] and reconnects[-1] >= 3:
            indicators.append("Reconnect frequency increasing")
        if len(fps) >= 2 and fps[-1] < fps[0] * 0.75:
            indicators.append("Average decoded FPS deteriorating")
        if len(latency) >= 2 and latency[-1] > max(500, latency[0] * 1.5):
            indicators.append("Connection latency rising")
        if outages >= 2:
            indicators.append("Repeated aggregated outages")
        if sum(item.freeze_events for item in samples) >= 2:
            indicators.append("Persistent frozen-frame events")
        if not indicators:
            existing = self.session.scalar(
                select(MaintenanceFinding).where(
                    MaintenanceFinding.camera_id == camera.id,
                    MaintenanceFinding.finding_key == "seven_day_stability_trend",
                    MaintenanceFinding.status == "open",
                )
            )
            if existing:
                existing.status = "resolved"
                existing.last_detected_at = datetime.now(UTC)
            return
        risk = "high" if len(indicators) >= 3 or outages >= 3 else "medium"
        criticality = (
            "critical"
            if any(tag.lower() in {"critical", "corridor"} for tag in camera.tags)
            else "high"
        )
        now = datetime.now(UTC)
        finding = self.session.scalar(
            select(MaintenanceFinding).where(
                MaintenanceFinding.camera_id == camera.id,
                MaintenanceFinding.finding_key == "seven_day_stability_trend",
            )
        )
        if not finding:
            finding = MaintenanceFinding(
                camera_id=camera.id,
                finding_key="seven_day_stability_trend",
                first_detected_at=now,
            )
            self.session.add(finding)
        finding.risk = risk
        finding.priority = criticality
        finding.status = "open"
        finding.indicators = indicators
        finding.explanation = (
            "Rule-based trend finding from persisted aggregate telemetry; this is maintenance "
            "risk, not an ML failure probability."
        )
        finding.last_detected_at = now

    def _refresh_incidents(self) -> None:
        cameras = list(self.session.scalars(select(Camera)))
        severe_by_edge: dict[str, list[str]] = defaultdict(list)
        severe_individual: list[tuple[Camera, CameraHealthAggregate]] = []
        for camera in cameras:
            samples = list(
                self.session.scalars(
                    select(CameraHealthAggregate)
                    .where(CameraHealthAggregate.camera_id == camera.id)
                    .order_by(CameraHealthAggregate.bucket_start.desc())
                    .limit(2)
                )
            )
            if not samples or samples[0].health_state not in {"offline", "critical"}:
                continue
            edge = samples[0].edge_node_id
            if edge:
                severe_by_edge[edge].append(camera.id)
            if len(samples) >= 2 and all(
                item.health_state in {"offline", "critical"} for item in samples
            ):
                severe_individual.append((camera, samples[0]))
        grouped = {edge: ids for edge, ids in severe_by_edge.items() if len(ids) >= 3}
        grouped_ids = {camera_id for ids in grouped.values() for camera_id in ids}
        now = datetime.now(UTC)
        active_keys: set[str] = set()
        for edge, camera_ids in grouped.items():
            key = f"edge:{edge}:offline"
            active_keys.add(key)
            self._upsert_incident(
                key=key,
                incident_type="edge_node_outage",
                severity="critical",
                title=f"Edge node {edge} degraded or offline",
                explanation=f"One grouped incident represents {len(camera_ids)} affected cameras.",
                edge_node_id=edge,
                camera_ids=camera_ids,
                now=now,
            )
        for camera, sample in severe_individual:
            if camera.id in grouped_ids:
                continue
            key = f"camera:{camera.id}:{sample.health_state}"
            active_keys.add(key)
            self._upsert_incident(
                key=key,
                incident_type="persistent_camera_failure",
                severity="critical" if sample.health_state == "offline" else "high",
                title=f"{camera.camera_code} {sample.health_state}",
                explanation=(
                    "Raised after consecutive severe aggregate intervals to suppress "
                    "transient noise."
                ),
                edge_node_id=sample.edge_node_id,
                camera_ids=[camera.id],
                now=now,
            )
        open_incidents = list(
            self.session.scalars(select(HealthIncident).where(HealthIncident.status == "open"))
        )
        for incident in open_incidents:
            if incident.deduplication_key in active_keys:
                continue
            incident.status = "resolved"
            incident.last_detected_at = now
            self.session.add(
                AuditLog(
                    resource_type="health_incident",
                    resource_id=incident.id,
                    action="health.incident_resolved",
                    actor_id=self.actor_id,
                    request_id=self.request_id,
                    source="camera_health",
                    changes={"deduplication_key": incident.deduplication_key},
                )
            )

    def _upsert_incident(
        self,
        *,
        key: str,
        incident_type: str,
        severity: str,
        title: str,
        explanation: str,
        edge_node_id: str | None,
        camera_ids: list[str],
        now: datetime,
    ) -> None:
        incident = self.session.scalar(
            select(HealthIncident).where(HealthIncident.deduplication_key == key)
        )
        if not incident:
            incident = HealthIncident(
                deduplication_key=key,
                incident_type=incident_type,
                severity=severity,
                title=title,
                explanation=explanation,
                edge_node_id=edge_node_id,
                affected_camera_ids=camera_ids,
                first_detected_at=now,
                last_detected_at=now,
            )
            self.session.add(incident)
            self.session.flush()
            self.session.add(
                AuditLog(
                    resource_type="health_incident",
                    resource_id=incident.id,
                    action="health.incident_opened",
                    actor_id=self.actor_id,
                    request_id=self.request_id,
                    source="camera_health",
                    changes={"deduplication_key": key, "affected_cameras": len(camera_ids)},
                )
            )
        incident.severity = severity
        incident.status = "open"
        incident.title = title
        incident.explanation = explanation
        incident.edge_node_id = edge_node_id
        incident.affected_camera_ids = camera_ids
        incident.last_detected_at = now

    def _maintenance_read(self, finding: MaintenanceFinding) -> MaintenanceRead:
        camera = self.session.get(Camera, finding.camera_id)
        assert camera
        return MaintenanceRead(
            **{
                key: value
                for key, value in finding.__dict__.items()
                if not key.startswith("_") and key != "camera_id"
            },
            camera=camera_read(camera),
        )

    @staticmethod
    def _aggregate_read(aggregate: CameraHealthAggregate, camera: Camera) -> HealthAggregateRead:
        return HealthAggregateRead(
            **{
                key: value
                for key, value in aggregate.__dict__.items()
                if not key.startswith("_") and key != "camera_id"
            },
            camera=camera_read(camera),
        )

    @staticmethod
    def _state(payload: HealthAggregateCreate, camera: Camera) -> str:
        if camera.status == "maintenance":
            return "maintenance"
        if payload.availability < 0.20:
            return "offline"
        if (
            payload.authentication_failures > 0
            or payload.freeze_events >= 2
            or payload.decoder_errors >= 5
            or payload.frame_age_ms is not None
            and payload.frame_age_ms > 15_000
        ):
            return "critical"
        if (
            payload.availability < 0.90
            or payload.reconnect_count >= 3
            or payload.decoded_fps is not None
            and payload.decoded_fps < 5
            or payload.latency_ms is not None
            and payload.latency_ms > 1500
            or payload.image_quality_state in {"degraded", "possible_obstruction"}
            or payload.ai_worker_state in {"degraded", "offline"}
        ):
            return "degraded"
        if payload.source == "registry_heartbeat" and camera.health == "unknown":
            return "unknown"
        return "healthy"

    @staticmethod
    def _bucket(value: datetime, seconds: int) -> datetime:
        value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        timestamp = int(value.timestamp())
        return datetime.fromtimestamp(timestamp - timestamp % seconds, tz=UTC)
