"""FastAPI application factory.

The `app` object is the WSGI/ASGI entry point:
    uvicorn api.app:app --reload

The connection pool is managed via the lifespan context manager so it
is created once on startup and cleanly closed on shutdown.
"""
from contextlib import asynccontextmanager
from typing import Optional

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from core.config import settings

# Global connection pool — initialised in lifespan, used by routes
pool: Optional[asyncpg.Pool] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the asyncpg connection pool for the application lifetime."""
    global pool

    pool = await asyncpg.create_pool(
        user=settings.sandbox_user,
        password=settings.sandbox_password,
        database=settings.sandbox_db,
        host=settings.pg_host,
        port=settings.pg_port,
        min_size=5,
        max_size=20,
        command_timeout=60,
    )

    yield

    await pool.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from api.routes import health_router, query_router  # deferred to avoid circular

    application = FastAPI(
        title="Text2SQL API",
        description="Read-only SQL query endpoint for Olist e-commerce dataset",
        version="1.0.0",
        lifespan=lifespan,
    )

    application.include_router(health_router)
    application.include_router(query_router)

    @application.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Consistent JSON error envelope."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error": exc.detail},
        )

    return application


# Module-level app instance used by uvicorn / pytest
app = create_app()
