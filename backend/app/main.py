"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from app.config import get_settings


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

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env}

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
