from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import NotFoundError
from app.media.source import MediaSourceResolver
from app.models import AuditLog, Camera, ConnectionProfile
from app.schemas.streams import (
    StreamAggregateMetricsRead,
    StreamCapabilitiesRead,
    StreamSessionList,
    StreamSessionRead,
    StreamStartRequest,
    stream_session_read,
)
from app.stream_engine import StreamEngine
from app.stream_engine.types import (
    ProcessingCameraSummary,
    ProcessingProfileSummary,
    ProcessingSourceCandidate,
)


class StreamProcessingService:
    def __init__(
        self,
        session: Session,
        *,
        engine: StreamEngine,
        source_resolver: MediaSourceResolver,
        actor_id: str,
        request_id: str | None,
    ) -> None:
        self.session = session
        self.engine = engine
        self.source_resolver = source_resolver
        self.actor_id = actor_id
        self.request_id = request_id

    def _profile(self, camera_id: str, connection_id: str | None) -> ConnectionProfile:
        return self._profiles(camera_id, connection_id)[0]

    def _profiles(
        self,
        camera_id: str,
        connection_id: str | None,
        preferred_adapter: str | None = None,
    ) -> list[ConnectionProfile]:
        statement = (
            select(ConnectionProfile)
            .options(selectinload(ConnectionProfile.camera).selectinload(Camera.department))
            .where(ConnectionProfile.camera_id == camera_id)
        )
        if connection_id:
            statement = statement.where(ConnectionProfile.id == connection_id)
        else:
            statement = statement.where(ConnectionProfile.enabled.is_(True)).order_by(
                ConnectionProfile.priority,
                ConnectionProfile.name,
            )
        profiles = list(self.session.scalars(statement))
        if not connection_id and preferred_adapter:
            profiles = [
                profile for profile in profiles if profile.adapter_kind == preferred_adapter
            ]
        if not profiles:
            raise NotFoundError("connection_profile", connection_id or camera_id)
        return profiles

    @staticmethod
    def _summaries(
        profile: ConnectionProfile,
    ) -> tuple[ProcessingCameraSummary, ProcessingProfileSummary]:
        camera = profile.camera
        return (
            ProcessingCameraSummary(
                id=camera.id,
                camera_code=camera.camera_code,
                camera_name=camera.camera_name,
                department_id=camera.department_id,
                department_name=camera.department.name,
                district=camera.district,
                city=camera.city,
                latitude=camera.latitude,
                longitude=camera.longitude,
                vendor=camera.vendor,
                model=camera.model,
                camera_type=camera.camera_type,
                ai_capabilities=tuple(
                    str(item).strip().lower() for item in (camera.ai_capabilities or [])
                ),
            ),
            ProcessingProfileSummary(
                id=profile.id,
                name=profile.name,
                adapter_kind=profile.adapter_kind,
                stream_role=profile.stream_role,
                endpoint_display=profile.endpoint_display,
            ),
        )

    def _audit(self, profile: ConnectionProfile, action: str, changes: dict[str, Any]) -> None:
        self.session.add(
            AuditLog(
                resource_type="connection_profile",
                resource_id=profile.id,
                action=action,
                actor_id=self.actor_id,
                request_id=self.request_id,
                source="stream_engine",
                changes=changes,
            )
        )
        self.session.commit()

    def capabilities(self) -> StreamCapabilitiesRead:
        return StreamCapabilitiesRead.model_validate(self.engine.capabilities())

    def list_sessions(self) -> StreamSessionList:
        items = [stream_session_read(item) for item in self.engine.list()]
        return StreamSessionList(items=items, total=len(items))

    def get(self, camera_id: str) -> StreamSessionRead:
        return stream_session_read(self.engine.get(camera_id))

    def start(self, camera_id: str, request: StreamStartRequest) -> StreamSessionRead:
        profiles = self._profiles(
            camera_id,
            str(request.connection_id) if request.connection_id else None,
            request.preferred_adapter,
        )
        profile = profiles[0]
        source = self.source_resolver.resolve(profile)
        camera, profile_summary = self._summaries(profile)
        fallback_sources: list[ProcessingSourceCandidate] = []
        if request.connection_id is None and source.credential_lease is None:
            for fallback_profile in profiles[1:]:
                if fallback_profile.credential_reference_ciphertext:
                    continue
                try:
                    fallback = self.source_resolver.resolve(fallback_profile)
                except Exception:
                    continue
                _, fallback_summary = self._summaries(fallback_profile)
                fallback_sources.append(
                    ProcessingSourceCandidate(
                        profile=fallback_summary,
                        endpoint=fallback.endpoint,
                        source_kind=fallback.source_kind,
                        credential_lease=fallback.credential_lease,
                    )
                )
        try:
            snapshot = self.engine.start(
                camera=camera,
                profile=profile_summary,
                endpoint=source.endpoint,
                source_kind=source.source_kind,
                credential_lease=source.credential_lease,
                target_fps=request.target_fps,
                decode_fps=request.decode_fps,
                transport=request.transport,
                max_frame_age_ms=request.max_frame_age_ms,
                fallback_sources=fallback_sources,
            )
        except Exception:
            if source.credential_lease:
                source.credential_lease.close()
            for fallback in fallback_sources:
                if fallback.credential_lease:
                    fallback.credential_lease.close()
            raise
        try:
            if source.credential_lease and source.credential_lease.profile_id:
                self.session.add(
                    AuditLog(
                        resource_type="credential_profile",
                        resource_id=source.credential_lease.profile_id,
                        action="credential.used",
                        actor_id=self.actor_id,
                        request_id=self.request_id,
                        source="stream_engine",
                        changes={"connection_id": profile.id, "stream_id": snapshot.id},
                    )
                )
            self._audit(
                profile,
                "stream.started",
                {
                    "stream_id": snapshot.id,
                    "state": snapshot.state,
                    "decoder_backend": snapshot.decoder_backend,
                    "fallback_profile_ids": [item.profile.id for item in fallback_sources],
                },
            )
        except Exception:
            self.engine.stop(camera_id)
            raise
        return stream_session_read(snapshot)

    def stop(self, camera_id: str) -> StreamSessionRead:
        before = self.engine.get(camera_id)
        snapshot = self.engine.stop(camera_id)
        profile = self._profile(camera_id, before.profile.id)
        self._audit(profile, "stream.stopped", {"stream_id": snapshot.id})
        return stream_session_read(snapshot)

    def restart(self, camera_id: str, request: StreamStartRequest) -> StreamSessionRead:
        self.stop(camera_id)
        restarted = self.start(camera_id, request)
        profile = self._profile(camera_id, str(restarted.profile.id))
        self._audit(profile, "stream.restarted", {"stream_id": str(restarted.id)})
        return restarted

    def metrics(self) -> StreamAggregateMetricsRead:
        return StreamAggregateMetricsRead.model_validate(self.engine.metrics())
