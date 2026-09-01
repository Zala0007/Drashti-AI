from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors import BadRequestError, RegistryError
from app.federation import EndpointCipher, build_adapter_registry
from app.media import MediaRuntimeManager
from app.media.source import MediaSourceResolver
from app.repositories import CameraFilters, ConnectionFilters, CredentialFilters
from app.schemas.federation import AdapterKind, VerificationStatus
from app.schemas.registry import (
    CameraStatus,
    CameraType,
    ConnectivityType,
    HealthStatus,
    StreamProtocol,
)
from app.services import (
    CameraHealthService,
    CaseService,
    CoverageService,
    CredentialProfileService,
    FederationService,
    GovernmentFeedService,
    InvestigationService,
    MediaRuntimeService,
    RegistryService,
    ReIDService,
    StreamProcessingService,
    WatchlistService,
)
from app.services.government_feeds import GovernmentFeedCatalogueClient
from app.stream_engine import StreamEngine


def _endpoint_cipher(request: Request) -> EndpointCipher:
    settings = request.app.state.settings
    try:
        return EndpointCipher(
            settings.federation_encryption_key,
            key_id=settings.federation_encryption_key_id,
        )
    except ValueError as exc:
        raise RegistryError(
            code="FEDERATION_ENCRYPTION_INVALID",
            message="Federation endpoint encryption configuration is invalid",
            status_code=503,
        ) from exc


def get_actor_id(
    x_actor_id: Annotated[
        str | None, Header(alias="X-Actor-ID", min_length=1, max_length=160)
    ] = None,
) -> str:
    # Authentication/RBAC is a later module. This identifier makes prototype
    # mutations attributable without pretending that the header is authentication.
    return x_actor_id or "prototype-system"


def get_investigator_id(
    x_actor_id: Annotated[str, Header(alias="X-Actor-ID", min_length=3, max_length=160)],
    x_actor_role: Annotated[str, Header(alias="X-Actor-Role", min_length=3, max_length=60)],
) -> str:
    if x_actor_role.lower() not in {"investigator", "supervisor"}:
        raise RegistryError(
            code="INVESTIGATION_ROLE_REQUIRED",
            message="An investigator or supervisor role is required",
            status_code=403,
        )
    return x_actor_id


def get_event_publisher_id(
    x_actor_id: Annotated[str, Header(alias="X-Actor-ID", min_length=3, max_length=160)],
    x_actor_role: Annotated[str, Header(alias="X-Actor-Role", min_length=3, max_length=60)],
) -> str:
    if x_actor_role.lower() not in {"analytics", "investigator", "supervisor"}:
        raise RegistryError(
            code="ANPR_PUBLISHER_ROLE_REQUIRED",
            message="An analytics publisher role is required",
            status_code=403,
        )
    return x_actor_id


@dataclass(frozen=True, slots=True)
class ActorContext:
    actor_id: str
    role: str


def _role_context(actor_id: str, role: str, allowed: set[str], code: str) -> ActorContext:
    normalized = role.strip().lower()
    if normalized not in allowed:
        raise RegistryError(
            code=code,
            message=f"One of these roles is required: {', '.join(sorted(allowed))}",
            status_code=403,
        )
    return ActorContext(actor_id=actor_id, role=normalized)


def get_investigator_context(
    x_actor_id: Annotated[str, Header(alias="X-Actor-ID", min_length=3, max_length=160)],
    x_actor_role: Annotated[str, Header(alias="X-Actor-Role", min_length=3, max_length=60)],
) -> ActorContext:
    return _role_context(
        x_actor_id, x_actor_role, {"investigator", "supervisor"}, "INVESTIGATOR_ROLE_REQUIRED"
    )


def get_analytics_context(
    x_actor_id: Annotated[str, Header(alias="X-Actor-ID", min_length=3, max_length=160)],
    x_actor_role: Annotated[str, Header(alias="X-Actor-Role", min_length=3, max_length=60)],
) -> ActorContext:
    return _role_context(
        x_actor_id,
        x_actor_role,
        {"analytics", "operations", "supervisor"},
        "ANALYTICS_ROLE_REQUIRED",
    )


def get_operations_context(
    x_actor_id: Annotated[str, Header(alias="X-Actor-ID", min_length=3, max_length=160)],
    x_actor_role: Annotated[str, Header(alias="X-Actor-Role", min_length=3, max_length=60)],
) -> ActorContext:
    return _role_context(
        x_actor_id,
        x_actor_role,
        {"operations", "supervisor"},
        "OPERATIONS_ROLE_REQUIRED",
    )


def get_planner_context(
    x_actor_id: Annotated[str, Header(alias="X-Actor-ID", min_length=3, max_length=160)],
    x_actor_role: Annotated[str, Header(alias="X-Actor-Role", min_length=3, max_length=60)],
) -> ActorContext:
    return _role_context(
        x_actor_id,
        x_actor_role,
        {"planner", "supervisor"},
        "PLANNER_ROLE_REQUIRED",
    )


def get_reid_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor: Annotated[ActorContext, Depends(get_investigator_context)],
) -> ReIDService:
    return ReIDService(
        session,
        actor_id=actor.actor_id,
        request_id=getattr(request.state, "request_id", None),
        app_env=request.app.state.settings.app_env,
    )


def get_reid_ingest_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor: Annotated[ActorContext, Depends(get_analytics_context)],
) -> ReIDService:
    return ReIDService(
        session,
        actor_id=actor.actor_id,
        request_id=getattr(request.state, "request_id", None),
        app_env=request.app.state.settings.app_env,
    )


def get_case_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor: Annotated[ActorContext, Depends(get_investigator_context)],
) -> CaseService:
    return CaseService(
        session,
        actor_id=actor.actor_id,
        actor_role=actor.role,
        request_id=getattr(request.state, "request_id", None),
    )


def get_camera_health_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor: Annotated[ActorContext, Depends(get_operations_context)],
) -> CameraHealthService:
    return CameraHealthService(
        session,
        engine=request.app.state.stream_engine,
        actor_id=actor.actor_id,
        request_id=getattr(request.state, "request_id", None),
    )


def get_camera_health_ingest_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor: Annotated[ActorContext, Depends(get_analytics_context)],
) -> CameraHealthService:
    return CameraHealthService(
        session,
        engine=request.app.state.stream_engine,
        actor_id=actor.actor_id,
        request_id=getattr(request.state, "request_id", None),
    )


def get_coverage_service(
    session: Annotated[Session, Depends(get_db)],
    actor: Annotated[ActorContext, Depends(get_planner_context)],
) -> CoverageService:
    return CoverageService(session, actor_id=actor.actor_id)


def get_watchlist_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor: Annotated[ActorContext, Depends(get_operations_context)],
) -> WatchlistService:
    return WatchlistService(
        session,
        actor_id=actor.actor_id,
        request_id=getattr(request.state, "request_id", None),
    )


def get_investigation_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor_id: Annotated[str, Depends(get_investigator_id)],
) -> InvestigationService:
    return InvestigationService(
        session,
        actor_id=actor_id,
        request_id=getattr(request.state, "request_id", None),
        app_env=request.app.state.settings.app_env,
    )


def get_investigation_event_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor_id: Annotated[str, Depends(get_event_publisher_id)],
) -> InvestigationService:
    return InvestigationService(
        session,
        actor_id=actor_id,
        request_id=getattr(request.state, "request_id", None),
        app_env=request.app.state.settings.app_env,
    )


def get_registry_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> RegistryService:
    return RegistryService(
        session,
        actor_id=actor_id,
        request_id=getattr(request.state, "request_id", None),
    )


def get_federation_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> FederationService:
    settings = request.app.state.settings
    cipher = _endpoint_cipher(request)
    try:
        adapters = build_adapter_registry(
            allowed_cidrs=settings.federation_allowed_cidrs,
            media_root=settings.federation_media_root,
        )
    except ValueError as exc:
        raise RegistryError(
            code="FEDERATION_NETWORK_POLICY_INVALID",
            message="Federation network policy configuration is invalid",
            status_code=503,
        ) from exc
    return FederationService(
        session,
        adapters=adapters,
        cipher=cipher,
        probe_timeout_seconds=settings.federation_probe_timeout_seconds,
        actor_id=actor_id,
        request_id=getattr(request.state, "request_id", None),
    )


def get_government_feed_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> GovernmentFeedService:
    settings = request.app.state.settings
    try:
        adapters = build_adapter_registry(
            allowed_cidrs=settings.federation_allowed_cidrs,
            media_root=settings.federation_media_root,
        )
        client = GovernmentFeedCatalogueClient(
            catalogue_url=settings.government_feed_catalogue_url,
            allowed_cidrs=settings.federation_allowed_cidrs,
            timeout_seconds=settings.government_feed_catalogue_timeout_seconds,
            max_items=settings.government_feed_catalogue_max_items,
        )
    except ValueError as exc:
        raise RegistryError(
            code="GOVERNMENT_FEED_CONFIGURATION_INVALID",
            message="Government feed catalogue configuration is invalid",
            status_code=503,
        ) from exc
    return GovernmentFeedService(
        session,
        client=client,
        adapters=adapters,
        cipher=_endpoint_cipher(request),
        rtsp_hosts=settings.government_feed_rtsp_hosts,
        fallback_latitude=settings.government_feed_fallback_latitude,
        fallback_longitude=settings.government_feed_fallback_longitude,
        actor_id=actor_id,
        request_id=getattr(request.state, "request_id", None),
    )


def get_media_runtime_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> MediaRuntimeService:
    settings = request.app.state.settings
    manager: MediaRuntimeManager = request.app.state.media_runtime
    cipher = _endpoint_cipher(request)
    try:
        adapters = build_adapter_registry(
            allowed_cidrs=settings.federation_allowed_cidrs,
            media_root=settings.federation_media_root,
        )
    except ValueError as exc:
        raise RegistryError(
            code="FEDERATION_NETWORK_POLICY_INVALID",
            message="Federation network policy configuration is invalid",
            status_code=503,
        ) from exc
    return MediaRuntimeService(
        session,
        manager=manager,
        cipher=cipher,
        adapters=adapters,
        media_root=settings.federation_media_root,
        allowed_cidrs=settings.federation_allowed_cidrs,
        actor_id=actor_id,
        request_id=getattr(request.state, "request_id", None),
    )


def get_stream_processing_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> StreamProcessingService:
    settings = request.app.state.settings
    cipher = _endpoint_cipher(request)
    try:
        adapters = build_adapter_registry(
            allowed_cidrs=settings.federation_allowed_cidrs,
            media_root=settings.federation_media_root,
        )
        source_resolver = MediaSourceResolver(
            session,
            cipher=cipher,
            adapters=adapters,
            media_root=settings.federation_media_root,
            allowed_cidrs=settings.federation_allowed_cidrs,
        )
    except ValueError as exc:
        raise RegistryError(
            code="STREAM_NETWORK_POLICY_INVALID",
            message="Stream processing network policy configuration is invalid",
            status_code=503,
        ) from exc
    engine: StreamEngine = request.app.state.stream_engine
    return StreamProcessingService(
        session,
        engine=engine,
        source_resolver=source_resolver,
        actor_id=actor_id,
        request_id=getattr(request.state, "request_id", None),
    )


def get_stream_engine(request: Request) -> StreamEngine:
    """Return the process-wide engine without opening a database session.

    Continuous preview responses can remain open for hours. Keeping their
    dependency graph independent of ``get_db`` prevents those responses from
    occupying database resources needed by registry and federation requests.
    """
    return request.app.state.stream_engine


def get_credential_profile_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> CredentialProfileService:
    return CredentialProfileService(
        session,
        cipher=_endpoint_cipher(request),
        actor_id=actor_id,
        request_id=getattr(request.state, "request_id", None),
    )


def get_credential_filters(
    department_id: UUID | None = None,
    enabled: bool | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> CredentialFilters:
    return CredentialFilters(
        department_id=str(department_id) if department_id else None,
        enabled=enabled,
        search=search,
    )


def get_connection_filters(
    camera_id: UUID | None = None,
    adapter_kind: AdapterKind | None = None,
    verification_status: VerificationStatus | None = None,
    enabled: bool | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> ConnectionFilters:
    return ConnectionFilters(
        camera_id=str(camera_id) if camera_id else None,
        adapter_kind=str(adapter_kind) if adapter_kind else None,
        verification_status=str(verification_status) if verification_status else None,
        enabled=enabled,
        search=search,
    )


def get_camera_filters(
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    department_id: Annotated[str | None, Query(max_length=36)] = None,
    district: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    city: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    vendor: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    vms: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    camera_type: CameraType | None = None,
    status: CameraStatus | None = None,
    health: HealthStatus | None = None,
    connectivity_type: ConnectivityType | None = None,
    stream_protocol: StreamProtocol | None = None,
    ai_capability: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    ai_enabled: bool | None = None,
    tag: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    include_retired: bool = False,
    bbox: Annotated[
        str | None,
        Query(description="west,south,east,north in WGS84 decimal degrees"),
    ] = None,
    near_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    near_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_m: Annotated[float | None, Query(gt=0, le=1_000_000)] = None,
) -> CameraFilters:
    parsed_bbox: tuple[float, float, float, float] | None = None
    if bbox:
        try:
            values = tuple(float(value.strip()) for value in bbox.split(","))
        except ValueError as exc:
            raise BadRequestError(
                "INVALID_BBOX", "bbox must contain four comma-separated numbers"
            ) from exc
        if len(values) != 4:
            raise BadRequestError("INVALID_BBOX", "bbox must be west,south,east,north")
        west, south, east, north = values
        if not (-180 <= west <= 180 and -180 <= east <= 180):
            raise BadRequestError("INVALID_BBOX", "bbox longitudes must be -180 to 180")
        if not (-90 <= south <= 90 and -90 <= north <= 90 and south <= north):
            raise BadRequestError("INVALID_BBOX", "bbox latitudes are invalid or reversed")
        parsed_bbox = (west, south, east, north)

    nearby_values = (near_lat, near_lon, radius_m)
    if any(value is not None for value in nearby_values) and not all(
        value is not None for value in nearby_values
    ):
        raise BadRequestError(
            "INCOMPLETE_NEARBY_FILTER",
            "near_lat, near_lon and radius_m must be supplied together",
        )

    return CameraFilters(
        search=search,
        department_id=department_id,
        district=district,
        city=city,
        vendor=vendor,
        vms=vms,
        camera_type=camera_type.value if camera_type else None,
        status=status.value if status else None,
        health=health.value if health else None,
        connectivity_type=connectivity_type.value if connectivity_type else None,
        stream_protocol=stream_protocol.value if stream_protocol else None,
        ai_capability=ai_capability.lower() if ai_capability else None,
        ai_enabled=ai_enabled,
        tag=tag.lower() if tag else None,
        include_retired=include_retired,
        bbox=parsed_bbox,
        near_lat=near_lat,
        near_lon=near_lon,
        radius_m=radius_m,
    )
