from app.api.routes.advanced import router as advanced_router
from app.api.routes.ai_showcase import router as ai_showcase_router
from app.api.routes.credentials import router as credentials_router
from app.api.routes.federation import router as federation_router
from app.api.routes.health import router as health_router
from app.api.routes.investigation import router as investigation_router
from app.api.routes.media import router as media_router
from app.api.routes.registry import router as registry_router
from app.api.routes.streams import router as streams_router
from app.api.routes.visual_intelligence import router as visual_intelligence_router
from app.api.routes.watchlist import router as watchlist_router

__all__ = [
    "credentials_router",
    "advanced_router",
    "ai_showcase_router",
    "federation_router",
    "health_router",
    "investigation_router",
    "media_router",
    "registry_router",
    "streams_router",
    "visual_intelligence_router",
    "watchlist_router",
]
