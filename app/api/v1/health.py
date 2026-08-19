from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.db.session import check_database_health
from app.schemas.common import ComponentHealth, HealthResponse
from app.services.redis_client import check_redis_health

router = APIRouter(tags=["health"])


@router.get("/health/live", include_in_schema=False)
async def liveness() -> dict[str, str]:
    """Process is up. Deliberately dependency-free so a database blip cannot trigger a
    pod restart loop."""
    return {"status": "ok"}


@router.get("/health/ready", response_model=HealthResponse)
async def readiness(response: Response) -> HealthResponse:
    """Dependencies are reachable, so this replica can take traffic."""
    database_ok = await check_database_health()
    redis_ok = await check_redis_health()

    if not (database_ok and redis_ok):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if database_ok and redis_ok else "degraded",
        environment=settings.environment,
        components=ComponentHealth(database=database_ok, redis=redis_ok),
    )
