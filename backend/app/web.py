"""Security headers and single-page-app static file serving."""

from __future__ import annotations

import json
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
_DOCS_PATHS = ("/api/docs", "/api/redoc", "/api/openapi.json")


class SecurityHeaders(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        headers = response.headers
        path = request.url.path
        if not (self.settings.enable_api_docs and path.startswith(_DOCS_PATHS)):
            headers.setdefault("Content-Security-Policy", CSP)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")  # nothing here is for other sites to embed
        if self.settings.is_https:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if path.startswith("/api/"):
            headers.setdefault("Cache-Control", "no-store")
        return response


class BodySizeLimit:
    """Refuse request bodies over ``limit`` bytes (413) before the app reads them.

    Browsers always send Content-Length, so chunked request bodies (whose size is unknown up front) are
    refused with 411. Routes that take uploads also count bytes as they read (``read_body``)."""

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            declared = headers.get(b"content-length", b"")
            if b"chunked" in headers.get(b"transfer-encoding", b"").lower():
                await self._reject(send, 411, "Send the request with a Content-Length header.")
                return
            if declared.isdigit() and int(declared) > self.limit:
                await self._reject(send, 413, "The request is too large.")
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class SinglePageApp(StaticFiles):
    """Serve the built frontend; unknown non-API paths without a file extension get index.html."""

    def __init__(self, directory: Path) -> None:
        super().__init__(directory=directory, html=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or "." in path.rsplit("/", 1)[-1]:
                raise
            return self._cached(await super().get_response("index.html", scope), "index.html")
        if response.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
            return self._cached(await super().get_response("index.html", scope), "index.html")
        return self._cached(response, path)

    @staticmethod
    def _cached(response: Response, path: str) -> Response:
        """Built assets have content hashes in their names, so they never change: cache them for good. The page
        itself is checked every time, so a new release is picked up at once."""
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response
