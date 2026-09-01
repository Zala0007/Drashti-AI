from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import BadRequestError, ConflictError, NotFoundError
from app.models import (
    ANPREvent,
    AuditLog,
    Camera,
    CameraGraphEdge,
    InvestigationActivity,
    InvestigationCandidate,
    InvestigationCase,
    InvestigationObservation,
)
from app.schemas.investigation import (
    ActivityRead,
    ANPREventCreate,
    ANPREventRead,
    CameraSummary,
    CandidateRead,
    DemoScenarioRead,
    InvestigationCaseRead,
    InvestigationCreate,
    InvestigationList,
    InvestigationTransition,
    InvestigationWorkspace,
    ObservationRead,
    PredictionBacktestRead,
    PredictionBacktestStep,
    RouteSegmentRead,
    normalize_plate,
)
from app.services.investigation_engine import (
    CameraGraphService,
    bearing_degrees,
    compass_direction,
    correlation_score,
    haversine_m,
    plate_similarity,
    temporal_feasibility,
)
from app.services.watchlist import WatchlistService

ACTIVE_STATES = {
    "created",
    "searching_history",
    "target_located",
    "active_tracking",
    "target_temporarily_lost",
    "reacquired",
}
ALLOWED_TRANSITIONS = {
    "suspended": ACTIVE_STATES,
    "completed": ACTIVE_STATES | {"suspended"},
    "cancelled": ACTIVE_STATES | {"suspended"},
    "active_tracking": {"suspended", "target_temporarily_lost"},
}


class InvestigationService:
    def __init__(
        self,
        session: Session,
        *,
        actor_id: str,
        request_id: str | None,
        app_env: str,
    ) -> None:
        self.session = session
        self.actor_id = actor_id
        self.request_id = request_id
        self.app_env = app_env
        self.graph = CameraGraphService()

    def create(self, payload: InvestigationCreate) -> InvestigationWorkspace:
        target = normalize_plate(payload.target_plate)
        case = InvestigationCase(
            case_number=f"INV-{datetime.now(UTC).year}-{uuid4().hex[:6].upper()}",
            target_plate=target,
            target_plate_original=payload.target_plate,
            priority=payload.priority,
            reason=payload.reason,
            district=payload.district,
            status="searching_history",
            created_by=self.actor_id,
        )
        self.session.add(case)
        self.session.flush()
        self._activity(case, "investigation.created", f"Target search opened for {target}")
        events = self._historical_events(
            target,
            district=payload.district,
            start_time=payload.start_time,
            end_time=payload.end_time,
        )
        for event in events:
            self._correlate(case, event)
        self._recalculate(case)
        self._audit(
            case, "investigation.created", {"target_plate": target, "reason": payload.reason}
        )
        self._commit()
        return self.workspace(case.id)

    def list(self) -> InvestigationList:
        cases = list(
            self.session.scalars(
                select(InvestigationCase).order_by(InvestigationCase.updated_at.desc()).limit(100)
            )
        )
        return InvestigationList(
            items=[InvestigationCaseRead.model_validate(case) for case in cases],
            total=len(cases),
        )

    def workspace(self, case_id: str) -> InvestigationWorkspace:
        case = self._case(case_id)
        observations = list(
            self.session.scalars(
                select(InvestigationObservation)
                .options(
                    selectinload(InvestigationObservation.event),
                    selectinload(InvestigationObservation.camera),
                )
                .where(InvestigationObservation.investigation_id == case.id)
                .order_by(InvestigationObservation.observed_at)
            )
        )
        candidates = list(
            self.session.scalars(
                select(InvestigationCandidate)
                .options(selectinload(InvestigationCandidate.camera))
                .where(InvestigationCandidate.investigation_id == case.id)
                .order_by(InvestigationCandidate.rank)
            )
        )
        activity = list(
            self.session.scalars(
                select(InvestigationActivity)
                .where(InvestigationActivity.investigation_id == case.id)
                .order_by(InvestigationActivity.created_at.desc())
                .limit(50)
            )
        )
        accepted = [item for item in observations if item.status in {"confirmed", "probable"}]
        route_segments = []
        for left, right in zip(accepted, accepted[1:], strict=False):
            route_segments.append(
                RouteSegmentRead(
                    source_camera_id=UUID(left.camera_id),
                    destination_camera_id=UUID(right.camera_id),
                    coordinates=[
                        (left.camera.longitude, left.camera.latitude),
                        (right.camera.longitude, right.camera.latitude),
                    ],
                    method=(
                        "verified_camera_topology"
                        if case.graph_method == "verified_camera_topology"
                        else "inferred_geodesic_connector"
                    ),
                    confidence="high" if left.status == right.status == "confirmed" else "medium",
                )
            )
        latest = accepted[-1].camera if accepted else None
        movement = (
            compass_direction(bearing_degrees(accepted[-2].camera, accepted[-1].camera))
            if len(accepted) >= 2
            else None
        )
        gaps = []
        if route_segments and case.graph_method != "verified_camera_topology":
            gaps.append(
                "Verified road topology is unavailable; connectors indicate inferred "
                "movement, not continuous CCTV coverage."
            )
        if accepted and not candidates:
            gaps.append(
                "No operational downstream camera is available inside the bounded "
                "surveillance cone."
            )
        return InvestigationWorkspace(
            case=InvestigationCaseRead.model_validate(case),
            observations=[self._observation_read(item) for item in observations],
            candidates=[self._candidate_read(item) for item in candidates],
            route_segments=route_segments,
            activity=[ActivityRead.model_validate(item) for item in activity],
            first_seen_at=accepted[0].observed_at if accepted else None,
            last_seen_at=accepted[-1].observed_at if accepted else None,
            last_confirmed_camera=self._camera_summary(latest) if latest else None,
            movement_direction=movement,
            coverage_gaps=gaps,
            prediction_basis=(
                "Verified directed camera topology and live camera health"
                if case.graph_method == "verified_camera_topology"
                else "Bounded geospatial and directional fallback; no verified road-network claim"
            ),
            next_recalculation_seconds=30,
        )

    def ingest_event(self, payload: ANPREventCreate) -> dict[str, Any]:
        camera = self.session.get(Camera, str(payload.camera_id))
        if not camera:
            raise NotFoundError("camera", str(payload.camera_id))
        existing = self.session.scalar(
            select(ANPREvent).where(ANPREvent.source_event_id == payload.source_event_id)
        )
        if existing:
            alerts_created = WatchlistService(
                self.session,
                actor_id=self.actor_id,
                request_id=self.request_id,
            ).match_event(existing)
            if alerts_created:
                self.session.commit()
            return {
                "event": ANPREventRead.model_validate(existing),
                "cases_updated": 0,
                "alerts_created": alerts_created,
                "replayed": True,
            }
        event = ANPREvent(
            source_event_id=payload.source_event_id,
            camera_id=str(payload.camera_id),
            observed_at=self._utc(payload.observed_at),
            plate_text=payload.plate_text,
            normalized_plate=normalize_plate(payload.plate_text),
            plate_confidence=payload.plate_confidence,
            direction=payload.direction,
            vehicle_attributes=payload.vehicle_attributes,
            evidence_reference=payload.evidence_reference,
            model_version=payload.model_version,
            source=payload.source,
        )
        self.session.add(event)
        self.session.flush()
        cases = list(
            self.session.scalars(
                select(InvestigationCase).where(InvestigationCase.status.in_(ACTIVE_STATES))
            )
        )
        updated = 0
        for case in cases:
            if plate_similarity(case.target_plate, event.normalized_plate) < 0.72:
                continue
            correlated = self._correlate(case, event)
            if correlated:
                previous_state = case.status
                self._recalculate(case)
                if previous_state == "target_temporarily_lost":
                    case.status = "reacquired"
                    self._activity(
                        case, "target.reacquired", f"Target reacquired at {camera.camera_code}"
                    )
                updated += 1
        alerts_created = WatchlistService(
            self.session,
            actor_id=self.actor_id,
            request_id=self.request_id,
        ).match_event(event)
        self.session.commit()
        return {
            "event": ANPREventRead.model_validate(event),
            "cases_updated": updated,
            "alerts_created": alerts_created,
            "replayed": False,
        }

    def transition(self, case_id: str, payload: InvestigationTransition) -> InvestigationWorkspace:
        case = self._case(case_id)
        if case.status not in ALLOWED_TRANSITIONS[payload.status]:
            raise ConflictError(
                "INVALID_INVESTIGATION_TRANSITION",
                f"Cannot transition from {case.status} to {payload.status}",
            )
        old = case.status
        case.status = payload.status
        case.ended_at = datetime.now(UTC) if payload.status in {"completed", "cancelled"} else None
        self._activity(
            case, "investigation.transitioned", f"State changed from {old} to {case.status}"
        )
        self._audit(
            case,
            "investigation.transitioned",
            {"old": old, "new": case.status, "reason": payload.reason},
        )
        self._commit()
        return self.workspace(case.id)

    def seed_demo(self, target_plate: str) -> DemoScenarioRead:
        if self.app_env == "production":
            raise BadRequestError(
                "DEMO_DISABLED", "Demonstration scenarios are disabled in production"
            )
        active_cameras = list(
            self.session.scalars(
                select(Camera).where(Camera.status == "active").order_by(Camera.camera_code)
            )
        )
        cameras = self._demo_observation_cameras(active_cameras, size=3)
        if len(cameras) < 3:
            raise ConflictError(
                "DEMO_CAMERAS_UNAVAILABLE",
                "At least three active registered cameras are required for the "
                "demonstration scenario",
            )
        now = datetime.now(UTC)
        leg_1_seconds = max(180, round(haversine_m(cameras[0], cameras[1]) / 13.9))
        leg_2_seconds = max(180, round(haversine_m(cameras[1], cameras[2]) / 13.9))
        observed_times = (
            now - timedelta(seconds=leg_1_seconds + leg_2_seconds + 120),
            now - timedelta(seconds=leg_2_seconds + 120),
            now - timedelta(seconds=120),
        )
        created = 0
        for index, (camera, observed_at) in enumerate(
            zip(cameras, observed_times, strict=True), start=1
        ):
            source_id = f"demo-sie-{target_plate}-{camera.id}-{index}"
            if self.session.scalar(
                select(ANPREvent.id).where(ANPREvent.source_event_id == source_id)
            ):
                continue
            observed_plate = target_plate if index != 2 else target_plate.replace("B", "8", 1)
            self.session.add(
                ANPREvent(
                    source_event_id=source_id,
                    camera_id=camera.id,
                    observed_at=observed_at,
                    plate_text=observed_plate,
                    normalized_plate=normalize_plate(observed_plate),
                    plate_confidence=0.97 if index != 2 else 0.86,
                    direction="north-east",
                    vehicle_attributes={"class": "car", "colour": "white", "demo": True},
                    evidence_reference=f"demo-evidence:{source_id}",
                    model_version="demo-fixture-v1",
                    source="demonstration_scenario",
                )
            )
            created += 1
        self.session.commit()
        return DemoScenarioRead(
            target_plate=target_plate,
            events_created=created,
            cameras_used=len(cameras),
            disclosure=(
                "Synthetic demonstration observations; never present these records "
                "as operational evidence."
            ),
        )

    def backtest(self, case_id: str) -> PredictionBacktestRead:
        case = self._case(case_id)
        observations = list(
            self.session.scalars(
                select(InvestigationObservation)
                .options(selectinload(InvestigationObservation.camera))
                .where(
                    InvestigationObservation.investigation_id == case.id,
                    InvestigationObservation.status.in_(("confirmed", "probable")),
                )
                .order_by(InvestigationObservation.observed_at)
            )
        )
        cameras = list(self.session.scalars(select(Camera)))
        edges = list(
            self.session.scalars(select(CameraGraphEdge).where(CameraGraphEdge.enabled.is_(True)))
        )
        steps: list[PredictionBacktestStep] = []
        for index in range(len(observations) - 1):
            anchor = observations[index]
            actual = observations[index + 1]
            previous = observations[index - 1].camera if index > 0 else None
            ranked = self.graph.rank_next_cameras(
                anchor=anchor.camera,
                previous=previous,
                cameras=cameras,
                edges=edges,
                max_candidates=12,
            )
            actual_rank = next(
                (
                    candidate_index
                    for candidate_index, candidate in enumerate(ranked, start=1)
                    if candidate.camera.id == actual.camera_id
                ),
                None,
            )
            steps.append(
                PredictionBacktestStep(
                    anchor_camera=self._camera_summary(anchor.camera),
                    actual_next_camera=self._camera_summary(actual.camera),
                    actual_rank=actual_rank,
                    candidate_count=len(ranked),
                    graph_method=(ranked[0].graph_method if ranked else "no_eligible_candidate"),
                    hit_at_1=actual_rank == 1,
                    hit_at_3=actual_rank is not None and actual_rank <= 3,
                    hit_at_5=actual_rank is not None and actual_rank <= 5,
                )
            )
        eligible = max(0, len(observations) - 1)
        evaluated = len(steps)

        def accuracy(attribute: str) -> float | None:
            if not evaluated:
                return None
            return round(sum(bool(getattr(step, attribute)) for step in steps) / evaluated, 4)

        return PredictionBacktestRead(
            case_id=case.id,
            eligible_transitions=eligible,
            evaluated_transitions=evaluated,
            top_1_accuracy=accuracy("hit_at_1"),
            top_3_accuracy=accuracy("hit_at_3"),
            top_5_accuracy=accuracy("hit_at_5"),
            coverage=round(evaluated / eligible, 4) if eligible else 0.0,
            evaluation_basis=(
                "Retrospective replay of accepted observations using the current verified "
                "camera graph, camera health, and bounded geospatial fallback. This is an "
                "engineering metric, not a probability that the target is at a camera."
            ),
            steps=steps,
        )

    @staticmethod
    def _demo_observation_cameras(cameras: list[Camera], *, size: int) -> list[Camera]:
        if len(cameras) <= size:
            return cameras
        best: tuple[float, list[Camera]] | None = None
        for anchor in cameras:
            neighbours = sorted(
                (camera for camera in cameras if camera.id != anchor.id),
                key=lambda camera: haversine_m(anchor, camera),
            )
            # Keep the closest operational neighbor unseen so the judge scenario
            # demonstrates a real next-camera candidate instead of consuming every
            # local camera as historical evidence.
            observations = neighbours[1:size]
            score = sum(haversine_m(anchor, camera) for camera in neighbours[:size])
            cluster = [*reversed(observations), anchor]
            if best is None or score < best[0]:
                best = (score, cluster)
        assert best is not None
        return best[1]

    def _historical_events(
        self,
        target: str,
        *,
        district: str | None,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> list[ANPREvent]:
        statement = (
            select(ANPREvent)
            .join(ANPREvent.camera)
            .options(selectinload(ANPREvent.camera))
            .where(
                or_(
                    ANPREvent.normalized_plate == target,
                    ANPREvent.normalized_plate.startswith(target[:2]),
                )
            )
        )
        if district:
            statement = statement.where(func.lower(Camera.district) == district.lower())
        if start_time:
            statement = statement.where(ANPREvent.observed_at >= self._utc(start_time))
        if end_time:
            statement = statement.where(ANPREvent.observed_at <= self._utc(end_time))
        candidates = list(
            self.session.scalars(statement.order_by(ANPREvent.observed_at).limit(1000))
        )
        return [
            event
            for event in candidates
            if plate_similarity(target, event.normalized_plate) >= 0.72
        ]

    def _correlate(self, case: InvestigationCase, event: ANPREvent) -> bool:
        existing = self.session.scalar(
            select(InvestigationObservation.id).where(
                InvestigationObservation.investigation_id == case.id,
                InvestigationObservation.event_id == event.id,
            )
        )
        if existing:
            return False
        previous = self.session.scalar(
            select(InvestigationObservation)
            .options(selectinload(InvestigationObservation.camera))
            .where(
                InvestigationObservation.investigation_id == case.id,
                InvestigationObservation.status.in_(("confirmed", "probable")),
                InvestigationObservation.observed_at <= event.observed_at,
            )
            .order_by(InvestigationObservation.observed_at.desc())
            .limit(1)
        )
        temporal, temporal_reason = temporal_feasibility(
            previous.camera if previous else None,
            event.camera,
            previous.observed_at if previous else None,
            event.observed_at,
        )
        similarity = plate_similarity(case.target_plate, event.normalized_plate)
        vehicle_similarity = event.vehicle_attributes.get("appearance_similarity")
        if not isinstance(vehicle_similarity, (int, float)):
            vehicle_similarity = None
        score = correlation_score(
            plate=similarity,
            ocr_confidence=event.plate_confidence,
            temporal=temporal,
            route=temporal,
            vehicle_similarity=vehicle_similarity,
        )
        status = (
            "rejected"
            if temporal == 0 or score < 0.60
            else "confirmed"
            if score >= 0.86 and similarity >= 0.90
            else "probable"
            if score >= 0.72
            else "candidate"
        )
        reasoning = [
            f"plate similarity {similarity:.2f}",
            f"OCR confidence {event.plate_confidence:.2f}",
            temporal_reason,
        ]
        if vehicle_similarity is not None:
            reasoning.append("vehicle appearance similarity supplied by analytics")
        self.session.add(
            InvestigationObservation(
                investigation_id=case.id,
                event_id=event.id,
                camera_id=event.camera_id,
                observed_at=event.observed_at,
                plate_similarity=similarity,
                temporal_feasibility=temporal,
                route_feasibility=temporal,
                correlation_score=score,
                status=status,
                reasoning=reasoning,
            )
        )
        self.session.flush()
        self._activity(
            case,
            f"observation.{status}",
            f"{status.title()} observation at {event.camera.camera_code}",
            {"event_id": event.id, "correlation_score": score},
        )
        return True

    def _recalculate(self, case: InvestigationCase) -> None:
        accepted = list(
            self.session.scalars(
                select(InvestigationObservation)
                .options(selectinload(InvestigationObservation.camera))
                .where(
                    InvestigationObservation.investigation_id == case.id,
                    InvestigationObservation.status.in_(("confirmed", "probable")),
                )
                .order_by(InvestigationObservation.observed_at)
            )
        )
        self.session.execute(
            delete(InvestigationCandidate).where(InvestigationCandidate.investigation_id == case.id)
        )
        if not accepted:
            case.status = "searching_history"
            case.latest_camera_id = None
            case.graph_method = "awaiting_anchor"
            case.route_confidence = "unavailable"
            case.last_recalculated_at = datetime.now(UTC)
            return
        anchor = accepted[-1].camera
        previous = accepted[-2].camera if len(accepted) >= 2 else None
        cameras = list(
            self.session.scalars(
                select(Camera)
                .options(selectinload(Camera.department))
                .where(Camera.status != "retired")
            )
        )
        edges = list(
            self.session.scalars(select(CameraGraphEdge).where(CameraGraphEdge.enabled.is_(True)))
        )
        ranked = self.graph.rank_next_cameras(
            anchor=anchor,
            previous=previous,
            cameras=cameras,
            edges=edges,
        )
        for rank, item in enumerate(ranked, start=1):
            uncertainty = max(45, round(item.travel_seconds * 0.35))
            self.session.add(
                InvestigationCandidate(
                    investigation_id=case.id,
                    anchor_camera_id=anchor.id,
                    camera_id=item.camera.id,
                    rank=rank,
                    tier=item.tier,
                    score=item.score,
                    confidence=item.confidence,
                    eta_min_seconds=max(20, item.travel_seconds - uncertainty),
                    eta_max_seconds=item.travel_seconds + uncertainty,
                    distance_m=item.distance_m,
                    reasons=item.reasons,
                    graph_method=item.graph_method,
                )
            )
        case.status = "active_tracking"
        case.latest_camera_id = anchor.id
        case.graph_method = ranked[0].graph_method if ranked else "no_reachable_camera"
        case.route_confidence = (
            "high"
            if len(accepted) >= 2 and all(item.status == "confirmed" for item in accepted)
            else "medium"
        )
        case.last_recalculated_at = datetime.now(UTC)
        self.session.flush()
        self._activity(
            case,
            "prediction.recalculated",
            f"Surveillance cone recalculated from {anchor.camera_code}",
            {"candidate_count": len(ranked), "graph_method": case.graph_method},
        )

    def _case(self, case_id: str) -> InvestigationCase:
        case = self.session.get(InvestigationCase, case_id)
        if not case:
            raise NotFoundError("investigation", case_id)
        return case

    def _activity(
        self,
        case: InvestigationCase,
        activity_type: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            InvestigationActivity(
                investigation_id=case.id,
                activity_type=activity_type,
                actor_id=self.actor_id,
                summary=summary,
                details=details or {},
            )
        )

    def _audit(self, case: InvestigationCase, action: str, changes: dict[str, Any]) -> None:
        self.session.add(
            AuditLog(
                resource_type="investigation_case",
                resource_id=case.id,
                action=action,
                actor_id=self.actor_id,
                request_id=self.request_id,
                source="investigation_engine",
                changes=changes,
            )
        )

    def _commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(
                "INVESTIGATION_CONFLICT", "Investigation state changed concurrently"
            ) from exc

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _camera_summary(camera: Camera) -> CameraSummary:
        return CameraSummary.model_validate(camera)

    def _observation_read(self, observation: InvestigationObservation) -> ObservationRead:
        return ObservationRead(
            id=UUID(observation.id),
            event=ANPREventRead.model_validate(observation.event),
            camera=self._camera_summary(observation.camera),
            plate_similarity=observation.plate_similarity,
            temporal_feasibility=observation.temporal_feasibility,
            route_feasibility=observation.route_feasibility,
            correlation_score=observation.correlation_score,
            status=observation.status,
            reasoning=observation.reasoning,
        )

    def _candidate_read(self, candidate: InvestigationCandidate) -> CandidateRead:
        return CandidateRead(
            id=UUID(candidate.id),
            camera=self._camera_summary(candidate.camera),
            anchor_camera_id=UUID(candidate.anchor_camera_id),
            rank=candidate.rank,
            tier=candidate.tier,
            confidence=candidate.confidence,
            eta_min_seconds=candidate.eta_min_seconds,
            eta_max_seconds=candidate.eta_max_seconds,
            distance_m=candidate.distance_m,
            reasons=candidate.reasons,
            graph_method=candidate.graph_method,
        )
