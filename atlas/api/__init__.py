"""HTTP edge: REST + SSE routes, plus the spec-shaped A2A HTTP+JSON binding (/v1)."""

from atlas.api.binding import v1_router
from atlas.api.routes import router, wellknown_router

__all__ = ["router", "wellknown_router", "v1_router"]
