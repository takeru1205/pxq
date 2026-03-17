"""API routers for pxq server."""

from fastapi import APIRouter

from pxq.api.health import router as health_router
from pxq.api.jobs import router as jobs_router

# Internal API router (for CLI and programmatic access)
internal_router = APIRouter(prefix="/api", tags=["internal"])

# Register sub-routers
internal_router.include_router(health_router)
internal_router.include_router(jobs_router)

__all__ = ["internal_router"]
