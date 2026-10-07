"""A single error shape for the API: ``{"detail": str, "errors"?: [{"path"|"field", "message"}]}``."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        detail: str,
        *,
        errors: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status, self.detail, self.errors, self.headers, self.extra = status, detail, errors, headers, extra


def _loc_to_field(loc: tuple[Any, ...]) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(parts) or "request"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        body: dict[str, Any] = {"detail": exc.detail}
        if exc.errors:
            body["errors"] = exc.errors
        if exc.extra:
            body.update(exc.extra)
        return JSONResponse(body, status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": _loc_to_field(tuple(e.get("loc", ()))), "message": str(e.get("msg", "invalid"))}
            for e in exc.errors()
        ]
        return JSONResponse({"detail": "Some fields are invalid.", "errors": errors}, status_code=422)
