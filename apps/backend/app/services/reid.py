from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BadRequestError, NotFoundError
from app.models import (
    ANPREvent,
    AuditLog,
    Camera,
    InvestigationActivity,
    InvestigationCase,
    InvestigationObservation,
    ReIDMatch,
    VehicleObservation,
)
from app.schemas.advanced import (
    DemoReIDRead,
    ReIDMatchRead,
    ReIDQuery,
    ReIDResult,
    ReIDReview,
    VehicleObservationCreate,
    VehicleObservationRead,
)
from app.schemas.investigation import normalize_plate
from app.services.advanced_common import camera_read
from app.services.investigation import InvestigationService
from app.services.investigation_engine import haversine_m, plate_similarity, temporal_feasibility


class VehicleEmbeddingProvider(Protocol):
    name: str

    def compare(self, left: list[float], right: list[float]) -> float: ...


class StoredVectorEmbeddingProvider:
    """Compares supplied embeddings without coupling ingestion to a research model."""

    name = "stored-vector-cosine"

    def compare(self, left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return round(max(0.0, min(1.0, dot / (left_norm * right_norm))), 4)


@dataclass(frozen=True, slots=True)
class ReIDWeights:
    plate: float = 0.32
    visual: float = 0.30
    colour: float = 0.08
    vehicle_class: float = 0.08
    temporal: float = 0.10
    route: float = 0.08
    direction: float = 0.04


class ReIDService:
    def __init__(
        self,
        session: Session,
        *,
        actor_id: str,
        request_id: str | None,
        app_env: str,
        provider: VehicleEmbeddingProvider | None = None,
        weights: ReIDWeights | None = None,
    ) -> None:
        self.session = session
        self.actor_id = actor_id
        self.request_id = request_id
        self.app_env = app_env
        self.provider = provider or StoredVectorEmbeddingProvider()
        self.weights = weights or ReIDWeights()

    def ingest(self, payload: VehicleObservationCreate) -> VehicleObservationRead:
        camera = self.session.get(Camera, str(payload.camera_id))
        if not camera:
            raise NotFoundError("camera", str(payload.camera_id))
        if payload.anpr_event_id and not self.session.get(ANPREvent, str(payload.anpr_event_id)):
            raise NotFoundError("anpr_event", str(payload.anpr_event_id))
        existing = self.session.scalar(
            select(VehicleObservation).where(
                VehicleObservation.source_observation_id == payload.source_observation_id
            )
        )
        if existing:
            if payload.anpr_event_id and not existing.anpr_event_id:
                existing.anpr_event_id = str(payload.anpr_event_id)
            if payload.plate_text:
                existing.plate_text = payload.plate_text
                existing.normalized_plate = normalize_plate(payload.plate_text)
            if payload.colour:
                existing.colour = payload.colour.lower()
            if payload.vehicle_class:
                existing.vehicle_class = payload.vehicle_class.lower()
            if payload.embedding is not None and payload.embedding_provider:
                existing.embedding = payload.embedding
                existing.embedding_provider = payload.embedding_provider
            if payload.crop_reference:
                existing.crop_reference = payload.crop_reference
            existing.quality_score = max(existing.quality_score, payload.quality_score)
            existing.quality_flags = list(
                dict.fromkeys(
                    [
                        *existing.quality_flags,
                        *(item.strip().lower() for item in payload.quality_flags),
                    ]
                )
            )
            existing.model_version = payload.model_version or existing.model_version
            self.session.commit()
            return self._read(existing, camera)
        flags = list(dict.fromkeys(item.strip().lower() for item in payload.quality_flags))
        embedding = payload.embedding
        if embedding is not None and payload.quality_score < 0.45:
            embedding = None
            flags.append("embedding_rejected_low_quality")
        if payload.bounding_box:
            width = payload.bounding_box[2] - payload.bounding_box[0]
            height = payload.bounding_box[3] - payload.bounding_box[1]
            if width < 48 or height < 32:
                embedding = None
                flags.append("embedding_rejected_small_crop")
        observation = VehicleObservation(
            source_observation_id=payload.source_observation_id,
            camera_id=camera.id,
            anpr_event_id=str(payload.anpr_event_id) if payload.anpr_event_id else None,
            observed_at=self._utc(payload.observed_at),
            track_id=payload.track_id,
            plate_text=payload.plate_text,
            normalized_plate=normalize_plate(payload.plate_text) if payload.plate_text else None,
            vehicle_class=payload.vehicle_class.lower() if payload.vehicle_class else None,
            colour=payload.colour.lower() if payload.colour else None,
            direction=payload.direction.lower() if payload.direction else None,
            bounding_box=payload.bounding_box,
            image_width=payload.image_width,
            image_height=payload.image_height,
            quality_score=payload.quality_score,
            quality_flags=list(dict.fromkeys(flags)),
            crop_reference=payload.crop_reference,
            embedding=embedding,
            embedding_provider=payload.embedding_provider if embedding is not None else None,
            model_version=payload.model_version,
            source=payload.source,
        )
        self.session.add(observation)
        self.session.commit()
        return self._read(observation, camera)

    def rank(self, investigation_id: str, query: ReIDQuery) -> ReIDResult:
        started = time.perf_counter()
        case = self.session.get(InvestigationCase, investigation_id)
        if not case:
            raise NotFoundError("investigation", investigation_id)
        target = self._target(case, query.target_observation_id)
        if target is None:
            return ReIDResult(
                investigation_id=case.id,
                target_observation_id=None,
                items=[],
                compared_observations=0,
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                disclosure="No quality-gated target vehicle profile is available.",
            )
        target_camera = self.session.get(Camera, target.camera_id)
        assert target_camera is not None
        anchor = self.session.scalar(
            select(InvestigationObservation)
            .where(
                InvestigationObservation.investigation_id == case.id,
                InvestigationObservation.status.in_(("confirmed", "probable")),
            )
            .order_by(InvestigationObservation.observed_at.desc())
            .limit(1)
        )
        anchor_camera = self.session.get(Camera, anchor.camera_id) if anchor else target_camera
        anchor_time = anchor.observed_at if anchor else target.observed_at
        start_time = self._utc(query.start_time) if query.start_time else anchor_time
        end_time = (
            self._utc(query.end_time) if query.end_time else anchor_time + timedelta(hours=12)
        )
        candidates = list(
            self.session.scalars(
                select(VehicleObservation)
                .where(
                    VehicleObservation.id != target.id,
                    VehicleObservation.observed_at >= start_time,
                    VehicleObservation.observed_at <= end_time,
                    VehicleObservation.quality_score >= 0.30,
                )
                .order_by(VehicleObservation.observed_at)
                .limit(500)
            )
        )
        ranked: list[tuple[ReIDMatch, VehicleObservation, Camera]] = []
        for candidate in candidates:
            camera = self.session.get(Camera, candidate.camera_id)
            if not camera or camera.status != "active":
                continue
            match = self._score(case, target, candidate, anchor_camera, anchor_time, camera)
            ranked.append((match, candidate, camera))
        ranked.sort(key=lambda item: (-item[0].technical_score, item[1].observed_at))
        selected = ranked[: query.max_candidates]
        self.session.commit()
        return ReIDResult(
            investigation_id=case.id,
            target_observation_id=target.id,
            items=[
                self._match_read(match, target, candidate, target_camera, camera)
                for match, candidate, camera in selected
            ],
            compared_observations=len(candidates),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            disclosure=(
                "Technical multi-signal ranking. HIGH/MEDIUM/LOW are uncalibrated "
                "assessments and never become confirmed evidence without investigator review."
            ),
        )

    def review(self, match_id: str, payload: ReIDReview) -> ReIDMatchRead:
        match = self.session.get(ReIDMatch, match_id)
        if not match:
            raise NotFoundError("reid_match", match_id)
        match.status = payload.status
        match.reviewed_by = self.actor_id
        match.reviewed_at = datetime.now(UTC)
        match.review_note = payload.note
        case = self.session.get(InvestigationCase, match.investigation_id)
        target = self.session.get(VehicleObservation, match.target_observation_id)
        candidate = self.session.get(VehicleObservation, match.candidate_observation_id)
        assert case and target and candidate
        if payload.status == "confirmed":
            self._attach_confirmed_observation(case, match, candidate)
        self.session.add(
            InvestigationActivity(
                investigation_id=case.id,
                activity_type=f"reid.{payload.status}",
                actor_id=self.actor_id,
                summary=(
                    f"Visual match {payload.status} for track {candidate.track_id or candidate.id}"
                ),
                details={"reid_match_id": match.id, "note": payload.note},
            )
        )
        self.session.add(
            AuditLog(
                resource_type="reid_match",
                resource_id=match.id,
                action=f"reid.{payload.status}",
                actor_id=self.actor_id,
                request_id=self.request_id,
                source="reid_engine",
                changes={"status": payload.status, "investigation_id": case.id},
            )
        )
        self.session.commit()
        target_camera = self.session.get(Camera, target.camera_id)
        candidate_camera = self.session.get(Camera, candidate.camera_id)
        assert target_camera and candidate_camera
        return self._match_read(match, target, candidate, target_camera, candidate_camera)

    def seed_demo(self, investigation_id: str) -> DemoReIDRead:
        if self.app_env == "production":
            raise BadRequestError(
                "DEMO_DISABLED", "Re-ID demonstration data is disabled in production"
            )
        case = self.session.get(InvestigationCase, investigation_id)
        if not case:
            raise NotFoundError("investigation", investigation_id)
        observations = list(
            self.session.scalars(
                select(InvestigationObservation)
                .where(
                    InvestigationObservation.investigation_id == case.id,
                    InvestigationObservation.status.in_(("confirmed", "probable")),
                )
                .order_by(InvestigationObservation.observed_at)
            )
        )
        if not observations:
            raise BadRequestError(
                "TARGET_PROFILE_UNAVAILABLE", "Investigation has no accepted observation"
            )
        target_link = observations[-1]
        target_event = self.session.get(ANPREvent, target_link.event_id)
        target_camera = self.session.get(Camera, target_link.camera_id)
        assert target_event and target_camera
        candidate_cameras = list(
            self.session.scalars(
                select(Camera).where(
                    Camera.id != target_camera.id,
                    Camera.status == "active",
                    Camera.health != "offline",
                )
            )
        )
        candidate_camera = min(
            candidate_cameras,
            key=lambda camera: haversine_m(target_camera, camera),
            default=None,
        )
        if not candidate_camera:
            raise BadRequestError(
                "CANDIDATE_CAMERA_UNAVAILABLE", "A second active camera is required"
            )
        target_source = f"demo-reid-target-{case.id}"
        candidate_source = f"demo-reid-candidate-{case.id}"
        decoy_source = f"demo-reid-decoy-{case.id}"
        created = 0
        target = self.session.scalar(
            select(VehicleObservation).where(
                VehicleObservation.source_observation_id == target_source
            )
        )
        if not target:
            target = VehicleObservation(
                source_observation_id=target_source,
                camera_id=target_camera.id,
                anpr_event_id=target_event.id,
                observed_at=target_event.observed_at,
                track_id=f"{target_camera.camera_code}-T041",
                plate_text=target_event.plate_text,
                normalized_plate=target_event.normalized_plate,
                vehicle_class="car",
                colour="white",
                direction=target_event.direction,
                bounding_box=[120, 80, 420, 270],
                image_width=640,
                image_height=360,
                quality_score=0.92,
                quality_flags=[],
                crop_reference=f"demo-crop:{target_source}",
                embedding=[0.71, 0.19, 0.42, 0.31, 0.38],
                embedding_provider="demonstration-vector-v1",
                model_version="synthetic-demo-profile-v1",
                source="demonstration_scenario",
            )
            self.session.add(target)
            created += 1
        distance_m = haversine_m(target_camera, candidate_camera)
        travel_seconds = max(35 * 60, int(distance_m / (70_000 / 3600) * 1.15))
        candidate_time = self._utc(target_link.observed_at) + timedelta(seconds=travel_seconds)
        unreadable_event_id = f"demo-reid-event-{case.id}"
        event = self.session.scalar(
            select(ANPREvent).where(ANPREvent.source_event_id == unreadable_event_id)
        )
        if not event:
            event = ANPREvent(
                source_event_id=unreadable_event_id,
                camera_id=candidate_camera.id,
                observed_at=candidate_time,
                plate_text="UNREADABLE",
                normalized_plate="UNREADABLE",
                plate_confidence=0.12,
                direction="north-east",
                vehicle_attributes={"class": "car", "colour": "white", "demo": True},
                evidence_reference=f"demo-evidence:{unreadable_event_id}",
                model_version="synthetic-demo-profile-v1",
                source="demonstration_scenario",
            )
            self.session.add(event)
            self.session.flush()
        for source_id, track, colour, embedding, at, linked_event in (
            (
                candidate_source,
                f"{candidate_camera.camera_code}-T102",
                "white",
                [0.69, 0.21, 0.41, 0.33, 0.37],
                candidate_time,
                event.id,
            ),
            (
                decoy_source,
                f"{candidate_camera.camera_code}-T084",
                "silver",
                [0.21, 0.74, 0.10, 0.42, 0.18],
                candidate_time - timedelta(minutes=2),
                None,
            ),
        ):
            if self.session.scalar(
                select(VehicleObservation.id).where(
                    VehicleObservation.source_observation_id == source_id
                )
            ):
                continue
            self.session.add(
                VehicleObservation(
                    source_observation_id=source_id,
                    camera_id=candidate_camera.id,
                    anpr_event_id=linked_event,
                    observed_at=at,
                    track_id=track,
                    plate_text=None,
                    normalized_plate=None,
                    vehicle_class="car",
                    colour=colour,
                    direction="north-east",
                    bounding_box=[98, 76, 405, 276],
                    image_width=640,
                    image_height=360,
                    quality_score=0.88,
                    quality_flags=["plate_unreadable"],
                    crop_reference=f"demo-crop:{source_id}",
                    embedding=embedding,
                    embedding_provider="demonstration-vector-v1",
                    model_version="synthetic-demo-profile-v1",
                    source="demonstration_scenario",
                )
            )
            created += 1
        self.session.commit()
        return DemoReIDRead(
            observations_created=created,
            disclosure=(
                "Synthetic Re-ID profiles for judge demonstration; not operational evidence."
            ),
        )

    def _target(
        self, case: InvestigationCase, requested_id: object | None
    ) -> VehicleObservation | None:
        if requested_id:
            target = self.session.get(VehicleObservation, str(requested_id))
            if not target:
                raise NotFoundError("vehicle_observation", str(requested_id))
            return target
        accepted_events = select(InvestigationObservation.event_id).where(
            InvestigationObservation.investigation_id == case.id,
            InvestigationObservation.status.in_(("confirmed", "probable")),
        )
        return self.session.scalar(
            select(VehicleObservation)
            .where(
                VehicleObservation.anpr_event_id.in_(accepted_events),
                VehicleObservation.embedding.is_not(None),
            )
            .order_by(VehicleObservation.observed_at.desc())
            .limit(1)
        )

    def _score(
        self,
        case: InvestigationCase,
        target: VehicleObservation,
        candidate: VehicleObservation,
        anchor_camera: Camera,
        anchor_time: datetime,
        candidate_camera: Camera,
    ) -> ReIDMatch:
        visual = (
            self.provider.compare(target.embedding, candidate.embedding)
            if target.embedding and candidate.embedding
            else None
        )
        plate = (
            plate_similarity(target.normalized_plate, candidate.normalized_plate)
            if target.normalized_plate and candidate.normalized_plate
            else None
        )
        colour = self._categorical(target.colour, candidate.colour)
        vehicle_class = self._categorical(target.vehicle_class, candidate.vehicle_class)
        temporal, temporal_reason = temporal_feasibility(
            anchor_camera, candidate_camera, anchor_time, candidate.observed_at
        )
        route = temporal
        direction = self._categorical(target.direction, candidate.direction)
        signals = {
            "plate": (plate, self.weights.plate),
            "visual": (visual, self.weights.visual),
            "colour": (colour, self.weights.colour),
            "vehicle_class": (vehicle_class, self.weights.vehicle_class),
            "temporal": (temporal, self.weights.temporal),
            "route": (route, self.weights.route),
            "direction": (direction, self.weights.direction),
        }
        available = [(value, weight) for value, weight in signals.values() if value is not None]
        denominator = sum(weight for _, weight in available) or 1
        score = round(sum(value * weight for value, weight in available) / denominator, 4)
        if temporal == 0:
            assessment, status = "low", "rejected"
        elif score >= 0.82 and (visual is None or visual >= 0.78):
            assessment, status = "high", "probable"
        elif score >= 0.64:
            assessment, status = "medium", "candidate"
        else:
            assessment, status = "low", "candidate"
        reasons = [temporal_reason]
        if visual is not None:
            reasons.append(f"visual embedding similarity {visual:.2f}")
        else:
            reasons.append("visual embedding unavailable; visual signal omitted")
        if plate is None:
            reasons.append("plate unavailable; ANPR signal omitted")
        if colour is not None:
            reasons.append("vehicle colour consistent" if colour == 1 else "vehicle colour differs")
        if vehicle_class is not None:
            reasons.append(
                "vehicle class consistent" if vehicle_class == 1 else "vehicle class differs"
            )
        match = self.session.scalar(
            select(ReIDMatch).where(
                ReIDMatch.investigation_id == case.id,
                ReIDMatch.target_observation_id == target.id,
                ReIDMatch.candidate_observation_id == candidate.id,
            )
        )
        if not match:
            match = ReIDMatch(
                investigation_id=case.id,
                target_observation_id=target.id,
                candidate_observation_id=candidate.id,
            )
            self.session.add(match)
        match.visual_similarity = visual
        match.plate_similarity = plate
        match.colour_similarity = colour
        match.class_similarity = vehicle_class
        match.temporal_feasibility = temporal
        match.route_feasibility = route
        match.direction_consistency = direction
        match.technical_score = score
        match.assessment = assessment
        if match.reviewed_at is None:
            match.status = status
        match.reasons = reasons
        self.session.flush()
        return match

    def _attach_confirmed_observation(
        self, case: InvestigationCase, match: ReIDMatch, candidate: VehicleObservation
    ) -> None:
        if not candidate.anpr_event_id:
            return
        existing = self.session.scalar(
            select(InvestigationObservation.id).where(
                InvestigationObservation.investigation_id == case.id,
                InvestigationObservation.event_id == candidate.anpr_event_id,
            )
        )
        if existing:
            return
        self.session.add(
            InvestigationObservation(
                investigation_id=case.id,
                event_id=candidate.anpr_event_id,
                camera_id=candidate.camera_id,
                observed_at=candidate.observed_at,
                plate_similarity=0,
                temporal_feasibility=match.temporal_feasibility,
                route_feasibility=match.route_feasibility,
                correlation_score=match.technical_score,
                status="confirmed",
                reasoning=[
                    "investigator-confirmed vehicle Re-ID match",
                    *match.reasons,
                ],
            )
        )
        self.session.flush()
        InvestigationService(
            self.session,
            actor_id=self.actor_id,
            request_id=self.request_id,
            app_env=self.app_env,
        )._recalculate(case)
        case.status = "reacquired"
        case.route_confidence = "high"

    def _match_read(
        self,
        match: ReIDMatch,
        target: VehicleObservation,
        candidate: VehicleObservation,
        target_camera: Camera,
        candidate_camera: Camera,
    ) -> ReIDMatchRead:
        values = {
            key: value
            for key, value in match.__dict__.items()
            if not key.startswith("_")
            and key not in {"target_observation_id", "candidate_observation_id"}
        }
        values.update(
            reviewed_by=match.reviewed_by,
            reviewed_at=match.reviewed_at,
            review_note=match.review_note,
        )
        return ReIDMatchRead(
            **values,
            target=self._read(target, target_camera),
            candidate=self._read(candidate, candidate_camera),
        )

    @staticmethod
    def _read(observation: VehicleObservation, camera: Camera) -> VehicleObservationRead:
        return VehicleObservationRead(
            id=observation.id,
            source_observation_id=observation.source_observation_id,
            camera=camera_read(camera),
            anpr_event_id=observation.anpr_event_id,
            observed_at=observation.observed_at,
            track_id=observation.track_id,
            plate_text=observation.plate_text,
            normalized_plate=observation.normalized_plate,
            vehicle_class=observation.vehicle_class,
            colour=observation.colour,
            direction=observation.direction,
            bounding_box=observation.bounding_box,
            image_width=observation.image_width,
            image_height=observation.image_height,
            quality_score=observation.quality_score,
            quality_flags=observation.quality_flags,
            crop_available=bool(observation.crop_reference),
            embedding_available=observation.embedding is not None,
            embedding_provider=observation.embedding_provider,
            model_version=observation.model_version,
            source=observation.source,
            created_at=observation.created_at,
        )

    @staticmethod
    def _categorical(left: str | None, right: str | None) -> float | None:
        if not left or not right:
            return None
        return 1.0 if left.strip().lower() == right.strip().lower() else 0.0

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
