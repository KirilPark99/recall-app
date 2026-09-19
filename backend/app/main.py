"""Сборка FastAPI-приложения."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, cards, discover, exports, folders, imports_api, me, media, sets, sharing, srs, stats, study, system, tts
from app.core.config import ensure_dirs, settings
from app.core.db import dispose_engine, get_engine, migrations_ready
from app.core.errors import install_error_handlers
from app.api.system import APP_VERSION

logger = logging.getLogger("recall")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    get_engine()
    if not await migrations_ready():
        logger.warning("Migrations are not applied or database integrity failed — run `alembic upgrade head`.")
    try:
        yield
    finally:
        await dispose_engine()


def create_app() -> FastAPI:
    ensure_dirs()
    app = FastAPI(
        title="Recall API",
        version=APP_VERSION,
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
        lifespan=_lifespan,
    )
    app.state.logger = logger
    install_error_handlers(app)

    if settings.cors_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        if settings.is_production:
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        logger.info("%s %s %s %dms rid=%s", request.method, request.url.path, response.status_code, duration_ms, request.state.request_id)
        return response

    api_prefix = "/api/v1"
    app.include_router(system.router, prefix=api_prefix)
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(me.router, prefix=api_prefix)
    app.include_router(sets.router, prefix=api_prefix)
    app.include_router(cards.router, prefix=api_prefix)
    app.include_router(folders.router, prefix=api_prefix)
    app.include_router(media.router, prefix=api_prefix)
    app.include_router(imports_api.router, prefix=api_prefix)
    app.include_router(exports.router, prefix=api_prefix)
    app.include_router(discover.router, prefix=api_prefix)
    app.include_router(sharing.router, prefix=api_prefix)
    app.include_router(study.router, prefix=api_prefix)
    app.include_router(srs.router, prefix=api_prefix)
    app.include_router(stats.router, prefix=api_prefix)
    app.include_router(admin.router, prefix=api_prefix)
    app.include_router(tts.router, prefix=api_prefix)

    # Production: раздача собранного frontend + SPA fallback.
    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str, request: Request):
            if full_path.startswith("api/"):
                return JSONResponse(
                    status_code=404,
                    content={"error": {"code": "NOT_FOUND", "message": "Неизвестный API-маршрут.", "details": {}, "request_id": request.state.request_id}},
                )
            candidate = frontend_dist / full_path
            if full_path and candidate.is_file():
                return _file_response(candidate)
            return _file_response(frontend_dist / "index.html")

    return app


def _file_response(path: Path):
    from fastapi.responses import FileResponse

    return FileResponse(path, headers={"Cache-Control": "no-cache"} if path.name == "index.html" else {"Cache-Control": "public, max-age=31536000, immutable"})


app = create_app()
