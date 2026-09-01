from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, NotFoundError
from app.models import ANPREvent, AuditLog, WatchlistAlert, WatchlistEntry
from app.schemas.investigation import normalize_plate
from app.schemas.watchlist import (
    WatchlistAlertAction,
    WatchlistAlertList,
    WatchlistAlertRead,
    WatchlistDashboard,
    WatchlistEntryCreate,
    WatchlistEntryList,
    WatchlistEntryRead,
    WatchlistEntryUpdate,
)


class WatchlistService:
    def __init__(
        self,
        session: Session,
        *,
        actor_id: str,
        request_id: str | None,
    ) -> None:
        self.session = session
        self.actor_id = actor_id
        self.request_id = request_id

    def create(self, payload: WatchlistEntryCreate) -> WatchlistEntryRead:
        normalized = normalize_plate(payload.plate_text)
        existing = self.session.scalar(
            select(WatchlistEntry).where(WatchlistEntry.normalized_plate == normalized)
        )
        if existing:
            raise ConflictError(
                "WATCHLIST_PLATE_EXISTS",
                "This registration is already present in the watchlist",
            )
        entry = WatchlistEntry(
            plate_text=payload.plate_text,
            normalized_plate=normalized,
            subject_label=payload.subject_label,
            reason=payload.reason,
            severity=payload.severity,
            status="active",
            valid_until=self._utc(payload.valid_until) if payload.valid_until else None,
            created_by=self.actor_id,
        )
        self.session.add(entry)
        self.session.flush()
        self._audit(
            "watchlist_entry",
            entry.id,
            "watchlist.entry.created",
            {"normalized_plate": normalized, "severity": entry.severity},
        )
        self._commit()
        return WatchlistEntryRead.model_validate(entry)

    def list_entries(self) -> WatchlistEntryList:
        items = list(
            self.session.scalars(
                select(WatchlistEntry).order_by(
                    WatchlistEntry.status.asc(), WatchlistEntry.updated_at.desc()
                )
            )
        )
        return WatchlistEntryList(
            items=[WatchlistEntryRead.model_validate(item) for item in items],
            total=len(items),
        )

    def update(self, entry_id: str, payload: WatchlistEntryUpdate) -> WatchlistEntryRead:
        entry = self.session.get(WatchlistEntry, entry_id)
        if not entry:
            raise NotFoundError("watchlist_entry", entry_id)
        previous = entry.status
        entry.status = payload.status
        if payload.reason is not None:
            entry.reason = payload.reason
        entry.valid_until = self._utc(payload.valid_until) if payload.valid_until else None
        self._audit(
            "watchlist_entry",
            entry.id,
            "watchlist.entry.updated",
            {"previous_status": previous, "status": entry.status},
        )
        self._commit()
        return WatchlistEntryRead.model_validate(entry)

    def match_event(self, event: ANPREvent) -> int:
        """Create an idempotent real-time alert for an exact active plate match."""

        observed_at = self._utc(event.observed_at)
        entry = self.session.scalar(
            select(WatchlistEntry).where(
                WatchlistEntry.status == "active",
                WatchlistEntry.normalized_plate == event.normalized_plate,
                WatchlistEntry.valid_from <= observed_at,
                or_(
                    WatchlistEntry.valid_until.is_(None),
                    WatchlistEntry.valid_until >= observed_at,
                ),
            )
        )
        if not entry:
            return 0
        existing = self.session.scalar(
            select(WatchlistAlert.id).where(
                WatchlistAlert.watchlist_entry_id == entry.id,
                WatchlistAlert.anpr_event_id == event.id,
            )
        )
        if existing:
            return 0
        alert = WatchlistAlert(
            watchlist_entry_id=entry.id,
            anpr_event_id=event.id,
            camera_id=event.camera_id,
            matched_plate=event.normalized_plate,
            match_score=1.0,
            status="new",
            observed_at=observed_at,
        )
        self.session.add(alert)
        self.session.flush()
        self._audit(
            "watchlist_alert",
            alert.id,
            "watchlist.alert.created",
            {
                "entry_id": entry.id,
                "anpr_event_id": event.id,
                "camera_id": event.camera_id,
                "match_score": 1.0,
            },
        )
        return 1

    def list_alerts(self, status: str | None = None) -> WatchlistAlertList:
        statement = (
            select(WatchlistAlert)
            .options(
                selectinload(WatchlistAlert.entry),
                selectinload(WatchlistAlert.event),
                selectinload(WatchlistAlert.camera),
            )
            .order_by(WatchlistAlert.observed_at.desc())
            .limit(200)
        )
        if status:
            statement = statement.where(WatchlistAlert.status == status)
        items = list(self.session.scalars(statement))
        unacknowledged = int(
            self.session.scalar(
                select(func.count()).select_from(WatchlistAlert).where(
                    WatchlistAlert.status == "new"
                )
            )
            or 0
        )
        return WatchlistAlertList(
            items=[self._alert_read(item) for item in items],
            total=len(items),
            unacknowledged=unacknowledged,
        )

    def update_alert(
        self, alert_id: str, payload: WatchlistAlertAction
    ) -> WatchlistAlertRead:
        alert = self.session.scalar(
            select(WatchlistAlert)
            .options(
                selectinload(WatchlistAlert.entry),
                selectinload(WatchlistAlert.event),
                selectinload(WatchlistAlert.camera),
            )
            .where(WatchlistAlert.id == alert_id)
        )
        if not alert:
            raise NotFoundError("watchlist_alert", alert_id)
        alert.status = payload.status
        alert.acknowledged_by = self.actor_id
        alert.acknowledged_at = datetime.now(UTC)
        self._audit(
            "watchlist_alert",
            alert.id,
            "watchlist.alert.reviewed",
            {"status": alert.status},
        )
        self._commit()
        return self._alert_read(alert)

    def dashboard(self) -> WatchlistDashboard:
        total = int(
            self.session.scalar(select(func.count()).select_from(WatchlistEntry)) or 0
        )
        active = int(
            self.session.scalar(
                select(func.count()).select_from(WatchlistEntry).where(
                    WatchlistEntry.status == "active"
                )
            )
            or 0
        )
        new_alerts = int(
            self.session.scalar(
                select(func.count()).select_from(WatchlistAlert).where(
                    WatchlistAlert.status == "new"
                )
            )
            or 0
        )
        latest = self.session.scalar(select(func.max(WatchlistAlert.observed_at)))
        return WatchlistDashboard(
            active_entries=active,
            total_entries=total,
            new_alerts=new_alerts,
            latest_alert_at=latest,
        )

    def _alert_read(self, alert: WatchlistAlert) -> WatchlistAlertRead:
        return WatchlistAlertRead(
            id=alert.id,
            status=alert.status,
            match_score=alert.match_score,
            matched_plate=alert.matched_plate,
            observed_at=alert.observed_at,
            acknowledged_by=alert.acknowledged_by,
            acknowledged_at=alert.acknowledged_at,
            created_at=alert.created_at,
            entry=WatchlistEntryRead.model_validate(alert.entry),
            anpr_event_id=alert.anpr_event_id,
            camera_id=alert.camera_id,
            camera_code=alert.camera.camera_code,
            camera_name=alert.camera.camera_name,
            district=alert.camera.district,
            evidence_reference=alert.event.evidence_reference,
            ocr_confidence=alert.event.plate_confidence,
        )

    def _audit(
        self, resource_type: str, resource_id: str, action: str, changes: dict[str, object]
    ) -> None:
        self.session.add(
            AuditLog(
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                actor_id=self.actor_id,
                request_id=self.request_id,
                source="watchlist_engine",
                changes=changes,
            )
        )

    def _commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(
                "WATCHLIST_CONFLICT", "Watchlist state changed concurrently"
            ) from exc

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
