from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.investigation import ANPREvent
from app.models.registry import Camera, TimestampMixin, utcnow, uuid_str


class WatchlistEntry(TimestampMixin, Base):
    __tablename__ = "watchlist_entries"
    __table_args__ = (Index("ix_watchlist_status_plate", "status", "normalized_plate"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    plate_text: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_plate: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    subject_label: Mapped[str] = mapped_column(String(160), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="high", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)


class WatchlistAlert(Base):
    __tablename__ = "watchlist_alerts"
    __table_args__ = (
        UniqueConstraint("watchlist_entry_id", "anpr_event_id", name="uq_watchlist_event"),
        Index("ix_watchlist_alert_status_time", "status", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    watchlist_entry_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("watchlist_entries.id", ondelete="CASCADE"), nullable=False
    )
    anpr_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("anpr_events.id", ondelete="RESTRICT"), nullable=False
    )
    camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False
    )
    matched_plate: Mapped[str] = mapped_column(String(20), nullable=False)
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="new", nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(160))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    entry: Mapped[WatchlistEntry] = relationship()
    event: Mapped[ANPREvent] = relationship()
    camera: Mapped[Camera] = relationship()
