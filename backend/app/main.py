"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db.base import check_pool_health


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="WRCC Social Media Marketing", version="0.1.0")

    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        """Something at the bare hostname.

        FastAPI serves nothing here by default, so pasting the API's domain
        into a browser returns a 404 — which reads as a dead deployment even
        when every route below it is fine. That is a bad first impression to
        give the person checking whether a deploy worked.

        Deliberately does not touch the database. This is the URL that uptime
        pings and crawlers hit most, and the connection pool on shared hosting
        is three deep; ``/api/health/ready`` is where that cost is paid, on
        purpose and only when asked.
        """
        return {
            "service": "WRCC Social Media Marketing API",
            "status": "ok",
            "health": "/api/health/ready",
            "docs": "/docs",
        }

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Liveness. Deliberately touches nothing but the process itself.

        This is the platform healthcheck (``railway.json``, and whatever
        replaces it), and a failing healthcheck restarts the container. Adding
        a database round-trip here would turn a brief connection blip into a
        restart loop, so the database signal lives on ``/ready`` instead.
        """
        return {"status": "ok", "env": settings.app_env}

    @app.get("/api/health/ready")
    async def ready() -> JSONResponse:
        """Readiness: the process is up *and* the database answers.

        Unauthenticated, because uptime monitors cannot log in — so the body
        says whether the database is reachable and nothing else. The exception
        text names a host, a port and often a user, and this endpoint is the
        one surface that would hand all three to an anonymous caller.
        """
        try:
            database_up = await check_pool_health()
        except Exception:  # noqa: BLE001 - any driver error means "not ready"
            database_up = False

        if not database_up:
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "database": "down"},
            )
        return JSONResponse(content={"status": "ready", "database": "up"})

    from app.api.content import router as content_router
    from app.api.courses import router as courses_router
    from app.api.images import router as images_router
    from app.api.public_media import router as public_media_router
    from app.api.publishing import router as publishing_router
    from app.auth.router import router as auth_router

    app.include_router(auth_router)
    app.include_router(content_router)
    app.include_router(images_router)
    app.include_router(publishing_router)
    # Unauthenticated by design — the networks fetch post images from it.
    app.include_router(public_media_router)
    app.include_router(courses_router)

    return app


app = create_app()
