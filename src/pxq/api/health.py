"""Health check endpoint for pxq server."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint.

    Returns
    -------
    dict[str, str]
        Health status response.
    """
    return {"status": "ok"}
