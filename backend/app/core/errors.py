"""Единый формат ошибок API."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers
        super().__init__(message)


def error_payload(code: str, message: str, details: dict[str, Any] | None, request_id: str) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        rid = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            status_code=exc.status,
            content=error_payload(exc.code, exc.message, exc.details, rid),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        rid = getattr(request.state, "request_id", str(uuid.uuid4()))
        details = []
        for err in exc.errors()[:20]:
            loc = ".".join(str(x) for x in err.get("loc", []))
            details.append({"field": loc, "message": str(err.get("msg", "invalid"))})
        return JSONResponse(
            status_code=422,
            content=error_payload("VALIDATION_ERROR", "Некорректные данные запроса.", {"items": details}, rid),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        rid = getattr(request.state, "request_id", str(uuid.uuid4()))
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT", 429: "RATE_LIMITED"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        message = exc.detail if isinstance(exc.detail, str) else "Ошибка запроса."
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code, message, {}, rid),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        rid = getattr(request.state, "request_id", str(uuid.uuid4()))
        # Секреты и заголовки не логируем — только тип исключения.
        request.app.state.logger.error("unhandled_exception request_id=%s type=%s", rid, type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "Внутренняя ошибка сервера.", {}, rid),
        )
