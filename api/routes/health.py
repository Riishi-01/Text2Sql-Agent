"""Health check route — GET /health"""
import time

from fastapi import APIRouter, HTTPException

from api.models import HealthResponse
from core.config import settings

router = APIRouter(tags=["System"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint with database ping.

    Returns database connection status and ping latency.
    """
    from api.app import pool  # imported here to avoid circular import at module load

    start = time.time()

    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")

        ping_ms = (time.time() - start) * 1000

        return HealthResponse(
            status="healthy",
            database=f"{settings.sandbox_db}@{settings.pg_host}",
            ping_ms=round(ping_ms, 2),
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Database connection failed: {str(e)}",
        )
