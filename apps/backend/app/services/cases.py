from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, RegistryError
from app.models import (
    ANPREvent,
    AuditLog,
    Camera,
    CaseActivity,
    CaseEvidence,
    CaseFile,
    HealthIncident,
    InvestigationCase,
    InvestigationObservation,
    ReIDMatch,
    VehicleObservation,
)
from app.schemas.advanced import (
    CaseActivityCreate,
    CaseActivityRead,
    CaseCreate,
    CaseExportRead,
    CaseList,
    CaseRead,
    CaseTransition,
    CaseWorkspace,
    EvidenceAttach,
    EvidenceRead,
)
from app.services.advanced_common import camera_read


class CaseService:
    def __init__(
        self,
        session: Session,
        *,
        actor_id: str,
        actor_role: str,
        request_id: str | None,
    ) -> None:
        self.session = session
        self.actor_id = actor_id
        self.actor_role = actor_role
        self.request_id = request_id

    def create(self, payload: CaseCreate) -> CaseWorkspace:
        investigation = None
        if payload.investigation_id:
            investigation = self.session.get(InvestigationCase, str(payload.investigation_id))
            if not investigation:
                raise NotFoundError("investigation", str(payload.investigation_id))
            existing = self.session.scalar(
                select(CaseFile).where(CaseFile.investigation_id == investigation.id)
            )
            if existing:
                raise ConflictError(
                    "INVESTIGATION_ALREADY_ATTACHED",
                    f"Investigation is already attached to case {existing.case_number}",
                )
        case = CaseFile(
            case_number=f"DRI-{datetime.now(UTC).year}-{uuid4().hex[:7].upper()}",
            title=payload.title,
            description=payload.description,
            case_type=payload.case_type,
            priority=payload.priority,
            status="active" if investigation else "open",
            created_by=self.actor_id,
            assigned_to=payload.assigned_to or self.actor_id,
            district=payload.district or (investigation.district if investigation else None),
            department=payload.department,
            authorization_reference=payload.authorization_reference,
            retention_class=payload.retention_class,
            investigation_id=investigation.id if investigation else None,
        )
        self.session.add(case)
        self.session.flush()
        self._activity(case, "case.created", f"Case {case.case_number} opened")
        self._audit(case, "case.created", {"investigation_id": case.investigation_id})
        if investigation:
            observations = list(
                self.session.scalars(
                    select(InvestigationObservation)
                    .where(
                        InvestigationObservation.investigation_id == investigation.id,
                        InvestigationObservation.status.in_(("confirmed", "probable")),
                    )
                    .order_by(InvestigationObservation.observed_at)
                )
            )
            for observation in observations:
                self._attach(
                    case,
                    EvidenceAttach(
                        source_type="investigation_observation",
                        source_id=observation.id,
                        evidence_type="vehicle_observation",
                        classification="restricted",
                        notes="Automatically linked from the authorized investigation.",
                    ),
                    commit=False,
                )
        self.session.commit()
        return self.workspace(case.id)

    def list(
        self,
        *,
        search: str | None,
        status: str | None,
        district: str | None,
        assigned_to: str | None,
        page: int,
        page_size: int,
    ) -> CaseList:
        statement = select(CaseFile)
        count_statement = select(func.count(CaseFile.id))
        conditions = []
        if self.actor_role != "supervisor":
            conditions.append(
                or_(
                    CaseFile.created_by == self.actor_id,
                    CaseFile.assigned_to == self.actor_id,
                )
            )
        if search:
            term = f"%{search.lower()}%"
            conditions.append(
                or_(
                    func.lower(CaseFile.case_number).like(term),
                    func.lower(CaseFile.title).like(term),
                    CaseFile.investigation_id.in_(
                        select(InvestigationCase.id).where(
                            func.lower(InvestigationCase.target_plate).like(term)
                        )
                    ),
                )
            )
        if status:
            conditions.append(CaseFile.status == status)
        if district:
            conditions.append(func.lower(CaseFile.district) == district.lower())
        if assigned_to:
            conditions.append(func.lower(CaseFile.assigned_to) == assigned_to.lower())
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        total = int(self.session.scalar(count_statement) or 0)
        items = list(
            self.session.scalars(
                statement.order_by(CaseFile.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return CaseList(items=[CaseRead.model_validate(item) for item in items], total=total)

    def workspace(self, case_id: str) -> CaseWorkspace:
        case = self._case(case_id)
        self._authorize_case(case)
        evidence = list(
            self.session.scalars(
                select(CaseEvidence)
                .where(CaseEvidence.case_id == case.id)
                .order_by(CaseEvidence.occurred_at, CaseEvidence.created_at)
            )
        )
        activities = list(
            self.session.scalars(
                select(CaseActivity)
                .where(CaseActivity.case_id == case.id)
                .order_by(CaseActivity.created_at.desc())
                .limit(500)
            )
        )
        investigation = (
            self.session.get(InvestigationCase, case.investigation_id)
            if case.investigation_id
            else None
        )
        route_cameras: list[Camera] = []
        if investigation:
            camera_ids = list(
                self.session.scalars(
                    select(InvestigationObservation.camera_id)
                    .where(
                        InvestigationObservation.investigation_id == investigation.id,
                        InvestigationObservation.status.in_(("confirmed", "probable")),
                    )
                    .order_by(InvestigationObservation.observed_at)
                )
            )
            route_cameras = [
                camera
                for camera_id in camera_ids
                if (camera := self.session.get(Camera, camera_id))
            ]
        return CaseWorkspace(
            case=CaseRead.model_validate(case),
            target_plate=investigation.target_plate if investigation else None,
            evidence=[self._evidence_read(item) for item in evidence],
            activity=[CaseActivityRead.model_validate(item) for item in activities],
            route_camera_sequence=[camera_read(camera) for camera in route_cameras],
            integrity_verified=sum(bool(item.sha256) for item in evidence),
            integrity_unavailable=sum(not item.sha256 for item in evidence),
        )

    def attach(self, case_id: str, payload: EvidenceAttach) -> CaseWorkspace:
        case = self._case(case_id)
        self._authorize_case(case)
        self._attach(case, payload, commit=True)
        return self.workspace(case.id)

    def record_activity(self, case_id: str, payload: CaseActivityCreate) -> CaseWorkspace:
        case = self._case(case_id)
        self._authorize_case(case)
        self._activity(case, payload.action, payload.summary, details=payload.details)
        self._audit(case, payload.action, payload.details)
        self.session.commit()
        return self.workspace(case.id)

    def view_evidence(self, case_id: str, evidence_id: str) -> EvidenceRead:
        case = self._case(case_id)
        self._authorize_case(case)
        evidence = self.session.get(CaseEvidence, evidence_id)
        if not evidence or evidence.case_id != case.id:
            raise NotFoundError("evidence", evidence_id)
        self._activity(
            case,
            "evidence.viewed",
            f"Evidence {evidence.id} metadata viewed",
            evidence_id=evidence.id,
        )
        self._audit(case, "evidence.viewed", {"evidence_id": evidence.id})
        self.session.commit()
        return self._evidence_read(evidence)

    def transition(self, case_id: str, payload: CaseTransition) -> CaseWorkspace:
        case = self._case(case_id)
        self._authorize_case(case)
        allowed = {
            "open": {"active", "archived"},
            "active": {"on_hold", "closed"},
            "on_hold": {"active", "closed"},
            "closed": {"active", "archived"},
            "archived": set(),
        }
        if payload.status not in allowed.get(case.status, set()):
            raise ConflictError(
                "INVALID_CASE_TRANSITION",
                f"Cannot transition case from {case.status} to {payload.status}",
            )
        previous = case.status
        case.status = payload.status
        self._activity(
            case,
            "case.transitioned",
            f"Case state changed from {previous} to {payload.status}",
            details={"reason": payload.reason},
        )
        self._audit(case, "case.transitioned", {"old": previous, "new": payload.status})
        self.session.commit()
        return self.workspace(case.id)

    def export(self, case_id: str) -> CaseExportRead:
        case = self._case(case_id)
        self._authorize_case(case)
        self._activity(case, "case.exported", "Structured case summary generated")
        self._audit(case, "case.exported", {"format": "structured_case_summary"})
        self.session.commit()
        workspace = self.workspace(case.id)
        return CaseExportRead(
            generated_at=datetime.now(UTC),
            generated_by=self.actor_id,
            integrity_disclosure=(
                "SHA-256 values verify the captured evidence manifest or referenced file "
                "bytes where supplied. This export alone is not a complete legal chain of custody."
            ),
            workspace=workspace,
        )

    def _attach(self, case: CaseFile, payload: EvidenceAttach, *, commit: bool) -> CaseEvidence:
        existing = self.session.scalar(
            select(CaseEvidence).where(
                CaseEvidence.case_id == case.id,
                CaseEvidence.source_type == payload.source_type,
                CaseEvidence.source_id == payload.source_id,
            )
        )
        if existing:
            return existing
        resolved = self._resolve_source(payload.source_type, payload.source_id)
        manifest = {
            "source_type": payload.source_type,
            "source_id": payload.source_id,
            "occurred_at": resolved["occurred_at"].isoformat(),
            "camera_id": resolved.get("camera_id"),
            "model_version": resolved.get("model_version"),
            "metadata": resolved.get("metadata", {}),
        }
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        evidence = CaseEvidence(
            case_id=case.id,
            source_type=payload.source_type,
            source_id=payload.source_id,
            camera_id=resolved.get("camera_id"),
            occurred_at=resolved["occurred_at"],
            evidence_type=payload.evidence_type,
            controlled_reference=resolved.get("controlled_reference"),
            sha256=digest,
            created_by=self.actor_id,
            model_version=resolved.get("model_version"),
            confidence=resolved.get("confidence"),
            classification=payload.classification,
            notes=payload.notes,
            metadata_json=resolved.get("metadata", {}),
        )
        self.session.add(evidence)
        self.session.flush()
        self._activity(
            case,
            "evidence.attached",
            f"{payload.evidence_type.replace('_', ' ').title()} attached",
            evidence_id=evidence.id,
            details={"source_type": payload.source_type, "sha256": digest},
        )
        self._audit(case, "evidence.attached", {"evidence_id": evidence.id})
        if commit:
            self.session.commit()
        return evidence

    def _resolve_source(self, source_type: str, source_id: str) -> dict[str, Any]:
        if source_type == "anpr_event":
            event = self.session.get(ANPREvent, source_id)
            if not event:
                raise NotFoundError("anpr_event", source_id)
            return self._event_source(event)
        if source_type == "investigation_observation":
            observation = self.session.get(InvestigationObservation, source_id)
            if not observation:
                raise NotFoundError("investigation_observation", source_id)
            event = self.session.get(ANPREvent, observation.event_id)
            assert event
            resolved = self._event_source(event)
            resolved["metadata"] = {
                **resolved["metadata"],
                "observation_status": observation.status,
                "correlation_score": observation.correlation_score,
                "reasoning": observation.reasoning,
            }
            return resolved
        if source_type == "reid_match":
            match = self.session.get(ReIDMatch, source_id)
            if not match:
                raise NotFoundError("reid_match", source_id)
            candidate = self.session.get(VehicleObservation, match.candidate_observation_id)
            assert candidate
            return {
                "occurred_at": candidate.observed_at,
                "camera_id": candidate.camera_id,
                "controlled_reference": candidate.crop_reference,
                "model_version": candidate.model_version,
                "confidence": match.technical_score,
                "metadata": {
                    "assessment": match.assessment,
                    "status": match.status,
                    "track_id": candidate.track_id,
                    "quality_score": candidate.quality_score,
                    "reviewed_by": match.reviewed_by,
                },
            }
        if source_type == "route_summary":
            investigation = self.session.get(InvestigationCase, source_id)
            if not investigation:
                raise NotFoundError("investigation", source_id)
            return {
                "occurred_at": investigation.last_recalculated_at or investigation.updated_at,
                "metadata": {
                    "investigation_id": investigation.id,
                    "target_plate": investigation.target_plate,
                    "graph_method": investigation.graph_method,
                    "route_confidence": investigation.route_confidence,
                },
            }
        if source_type == "alert":
            incident = self.session.get(HealthIncident, source_id)
            if not incident:
                raise NotFoundError("health_incident", source_id)
            return {
                "occurred_at": incident.first_detected_at,
                "metadata": {
                    "incident_type": incident.incident_type,
                    "severity": incident.severity,
                    "affected_camera_ids": incident.affected_camera_ids,
                },
            }
        raise RegistryError(
            code="EVIDENCE_SOURCE_UNSUPPORTED",
            message="Unsupported evidence source",
            status_code=422,
        )

    @staticmethod
    def _event_source(event: ANPREvent) -> dict[str, Any]:
        return {
            "occurred_at": event.observed_at,
            "camera_id": event.camera_id,
            "controlled_reference": event.evidence_reference,
            "model_version": event.model_version,
            "confidence": event.plate_confidence,
            "metadata": {
                "plate_text": event.plate_text,
                "normalized_plate": event.normalized_plate,
                "source": event.source,
                "vehicle_attributes": event.vehicle_attributes,
            },
        }

    def _evidence_read(self, evidence: CaseEvidence) -> EvidenceRead:
        camera = self.session.get(Camera, evidence.camera_id) if evidence.camera_id else None
        return EvidenceRead(
            id=evidence.id,
            case_id=evidence.case_id,
            source_type=evidence.source_type,
            source_id=evidence.source_id,
            camera=camera_read(camera) if camera else None,
            occurred_at=evidence.occurred_at,
            evidence_type=evidence.evidence_type,
            sha256=evidence.sha256,
            created_by=evidence.created_by,
            model_version=evidence.model_version,
            confidence=evidence.confidence,
            classification=evidence.classification,
            notes=evidence.notes,
            metadata=evidence.metadata_json,
            retrieval_available=bool(evidence.controlled_reference),
            created_at=evidence.created_at,
        )

    def _case(self, case_id: str) -> CaseFile:
        case = self.session.get(CaseFile, case_id)
        if not case:
            raise NotFoundError("case", case_id)
        return case

    def _authorize_case(self, case: CaseFile) -> None:
        if self.actor_role == "supervisor":
            return
        if self.actor_id not in {case.created_by, case.assigned_to}:
            raise RegistryError(
                code="CASE_ACCESS_DENIED",
                message="Case access is limited to the assigned investigator or supervisor",
                status_code=403,
            )

    def _activity(
        self,
        case: CaseFile,
        action: str,
        summary: str,
        *,
        evidence_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            CaseActivity(
                case_id=case.id,
                evidence_id=evidence_id,
                action=action,
                actor_id=self.actor_id,
                summary=summary,
                details=details or {},
            )
        )

    def _audit(self, case: CaseFile, action: str, changes: dict[str, Any]) -> None:
        self.session.add(
            AuditLog(
                resource_type="case_file",
                resource_id=case.id,
                action=action,
                actor_id=self.actor_id,
                request_id=self.request_id,
                source="case_management",
                changes=changes,
            )
        )
