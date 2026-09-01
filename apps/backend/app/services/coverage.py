from __future__ import annotations

import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import (
    Camera,
    CameraHealthAggregate,
    CoverageAnalysisRun,
    CoverageGap,
    DeploymentCandidate,
    InvestigationCandidate,
    InvestigationCase,
)
from app.schemas.advanced import (
    CoverageAnalysisRead,
    CoverageGapRead,
    CoverageRunRequest,
    CoverageWhatIfRead,
    CriticalCoverageNode,
    DeploymentCandidateRead,
)
from app.services.advanced_common import camera_read
from app.services.investigation_engine import haversine_m


class CoverageService:
    def __init__(self, session: Session, *, actor_id: str) -> None:
        self.session = session
        self.actor_id = actor_id

    def analyze(self, payload: CoverageRunRequest) -> CoverageAnalysisRead:
        started = time.perf_counter()
        statement = select(Camera).where(Camera.status != "retired")
        if payload.district:
            statement = statement.where(func.lower(Camera.district) == payload.district.lower())
        cameras = list(self.session.scalars(statement.order_by(Camera.camera_code)))
        run = CoverageAnalysisRun(
            district=payload.district,
            analysis_type="registry_health_location_analysis",
            assumptions=[
                "Camera coordinates are treated as surveyed points only where registry data "
                "is accurate.",
                "Coverage is directional only when range, bearing and field-of-view metadata "
                "exist.",
                "No road connectivity is claimed without verified camera graph or road topology.",
            ],
            camera_count=len(cameras),
            operational_count=0,
            duration_ms=0,
            created_by=self.actor_id,
        )
        self.session.add(run)
        self.session.flush()
        latest_health = {camera.id: self._latest_health(camera.id) for camera in cameras}
        operational = [
            camera for camera in cameras if self._is_operational(camera, latest_health[camera.id])
        ]
        offline = [camera for camera in cameras if camera not in operational]
        run.operational_count = len(operational)

        seen_pairs: set[tuple[str, str]] = set()
        gaps: list[CoverageGap] = []
        for camera in operational:
            nearest, distance = self._nearest(camera, operational)
            if not nearest or distance is None or distance <= payload.gap_threshold_m:
                continue
            pair = tuple(sorted((camera.id, nearest.id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            gaps.append(
                CoverageGap(
                    analysis_run_id=run.id,
                    gap_type="permanent",
                    severity="critical" if distance > payload.gap_threshold_m * 2 else "high",
                    latitude=(camera.latitude + nearest.latitude) / 2,
                    longitude=(camera.longitude + nearest.longitude) / 2,
                    radius_m=distance / 2,
                    source_camera_id=camera.id,
                    destination_camera_id=nearest.id,
                    explanation=(
                        f"{distance / 1000:.1f} km separates the nearest operational registry "
                        "nodes; road-segment coverage is not asserted."
                    ),
                    confidence_basis="location_based_coverage_estimate",
                )
            )
        for camera in offline:
            nearest, distance = self._nearest(camera, operational, include_anchor=True)
            if nearest and distance is not None and distance <= payload.redundancy_radius_m:
                continue
            gaps.append(
                CoverageGap(
                    analysis_run_id=run.id,
                    gap_type="temporary",
                    severity="critical",
                    latitude=camera.latitude,
                    longitude=camera.longitude,
                    radius_m=camera.coverage_radius_m or payload.redundancy_radius_m,
                    source_camera_id=camera.id,
                    destination_camera_id=nearest.id if nearest else None,
                    explanation=(
                        f"{camera.camera_code} is unavailable and no operational backup lies "
                        f"within {payload.redundancy_radius_m / 1000:.1f} km."
                    ),
                    confidence_basis="temporary_outage_location_estimate",
                )
            )
        self.session.add_all(gaps)
        self.session.flush()

        deployments: list[DeploymentCandidate] = []
        for gap in sorted(gaps, key=lambda item: (item.severity != "critical", -item.radius_m))[
            :20
        ]:
            candidate = DeploymentCandidate(
                analysis_run_id=run.id,
                latitude=gap.latitude,
                longitude=gap.longitude,
                priority="critical" if gap.severity == "critical" else "high",
                area_label=(
                    "Temporary resilience area"
                    if gap.gap_type == "temporary"
                    else "Registry gap midpoint area"
                ),
                reasons=[
                    f"{gap.gap_type.title()} coverage gap",
                    gap.explanation,
                    "Field survey and network feasibility review required",
                ],
                estimated_radius_m=min(gap.radius_m, 5000),
                assumption="candidate area only; not an exact installation coordinate",
            )
            deployments.append(candidate)
        self.session.add_all(deployments)
        critical_nodes = self._critical_nodes(operational, payload.redundancy_radius_m)
        run.duration_ms = round((time.perf_counter() - started) * 1000, 3)
        self.session.commit()
        return self._read(run, gaps, deployments, critical_nodes)

    def latest(self, district: str | None = None) -> CoverageAnalysisRead:
        statement = select(CoverageAnalysisRun)
        if district:
            statement = statement.where(
                func.lower(CoverageAnalysisRun.district) == district.lower()
            )
        else:
            statement = statement.where(CoverageAnalysisRun.district.is_(None))
        run = self.session.scalar(
            statement.order_by(CoverageAnalysisRun.created_at.desc()).limit(1)
        )
        if not run:
            return self.analyze(CoverageRunRequest(district=district))
        gaps = list(
            self.session.scalars(select(CoverageGap).where(CoverageGap.analysis_run_id == run.id))
        )
        deployments = list(
            self.session.scalars(
                select(DeploymentCandidate).where(DeploymentCandidate.analysis_run_id == run.id)
            )
        )
        statement_cameras = select(Camera).where(Camera.status != "retired")
        if run.district:
            statement_cameras = statement_cameras.where(
                func.lower(Camera.district) == run.district.lower()
            )
        operational = [
            camera
            for camera in self.session.scalars(statement_cameras)
            if self._is_operational(camera, self._latest_health(camera.id))
        ]
        return self._read(run, gaps, deployments, self._critical_nodes(operational, 5000))

    def what_if(self, camera_id: str) -> CoverageWhatIfRead:
        camera = self.session.get(Camera, camera_id)
        if not camera:
            raise NotFoundError("camera", camera_id)
        operational = [
            item
            for item in self.session.scalars(
                select(Camera).where(Camera.status == "active", Camera.id != camera.id)
            )
            if self._is_operational(item, self._latest_health(item.id))
        ]
        nearest, distance = self._nearest(camera, operational, include_anchor=True)
        radius = camera.coverage_radius_m or 1000.0
        affected = set(
            self.session.scalars(
                select(InvestigationCase.id).where(
                    InvestigationCase.latest_camera_id == camera.id,
                    InvestigationCase.status.in_(
                        ("active_tracking", "reacquired", "target_temporarily_lost")
                    ),
                )
            )
        )
        affected.update(
            self.session.scalars(
                select(InvestigationCandidate.investigation_id).where(
                    InvestigationCandidate.camera_id == camera.id
                )
            )
        )
        return CoverageWhatIfRead(
            camera=camera_read(camera),
            nearest_backup=camera_read(nearest) if nearest else None,
            nearest_backup_distance_m=round(distance, 2) if distance is not None else None,
            estimated_coverage_lost_radius_m=radius,
            critical_gap_created=distance is None or distance > max(5000, radius * 2),
            affected_investigation_ids=sorted(affected),
            assumptions=[
                "Simulation only; no camera or stream state was changed.",
                "Coverage loss uses registry radius when available, otherwise a 1 km "
                "planning default.",
                "Nearest backup is based on straight-line distance, not verified road visibility.",
            ],
        )

    def _read(
        self,
        run: CoverageAnalysisRun,
        gaps: list[CoverageGap],
        deployments: list[DeploymentCandidate],
        critical_nodes: list[CriticalCoverageNode],
    ) -> CoverageAnalysisRead:
        return CoverageAnalysisRead(
            id=run.id,
            district=run.district,
            analysis_type=run.analysis_type,
            assumptions=run.assumptions,
            camera_count=run.camera_count,
            operational_count=run.operational_count,
            duration_ms=run.duration_ms,
            created_by=run.created_by,
            created_at=run.created_at,
            gaps=[CoverageGapRead.model_validate(item) for item in gaps],
            deployment_candidates=[
                DeploymentCandidateRead.model_validate(item) for item in deployments
            ],
            critical_nodes=critical_nodes,
            metrics={
                "operational_nodes": run.operational_count,
                "permanent_gaps": sum(item.gap_type == "permanent" for item in gaps),
                "temporary_gaps": sum(item.gap_type == "temporary" for item in gaps),
                "critical_nodes": len(critical_nodes),
                "deployment_candidates": len(deployments),
            },
        )

    def _critical_nodes(
        self, operational: list[Camera], redundancy_radius_m: float
    ) -> list[CriticalCoverageNode]:
        result: list[CriticalCoverageNode] = []
        for camera in operational:
            nearest, distance = self._nearest(camera, operational)
            if distance is None or distance > redundancy_radius_m:
                result.append(
                    CriticalCoverageNode(
                        camera=camera_read(camera),
                        nearest_backup_distance_m=round(distance, 2)
                        if distance is not None
                        else None,
                        reason=(
                            "No operational camera lies inside the configured redundancy radius; "
                            "failure may create a temporary location-based gap."
                        ),
                    )
                )
        return result

    def _latest_health(self, camera_id: str) -> CameraHealthAggregate | None:
        return self.session.scalar(
            select(CameraHealthAggregate)
            .where(CameraHealthAggregate.camera_id == camera_id)
            .order_by(CameraHealthAggregate.bucket_start.desc())
            .limit(1)
        )

    @staticmethod
    def _is_operational(camera: Camera, health: CameraHealthAggregate | None) -> bool:
        if camera.status != "active":
            return False
        if health:
            return health.health_state in {"healthy", "degraded"}
        return camera.health in {"online", "degraded", "unknown"}

    @staticmethod
    def _nearest(
        anchor: Camera,
        candidates: list[Camera],
        *,
        include_anchor: bool = False,
    ) -> tuple[Camera | None, float | None]:
        distances = [
            (candidate, haversine_m(anchor, candidate))
            for candidate in candidates
            if include_anchor or candidate.id != anchor.id
        ]
        return min(distances, key=lambda item: item[1]) if distances else (None, None)
