"""Request-context observability (Item 4 — gated by OBSERVABILITY_ENABLED).

A per-request id (``X-Request-ID``) is stored in a contextvar so EVERY log line
emitted while handling a request carries the same id — making auth/session/request
flows traceable end-to-end. The middleware also times each request and logs
method / path / status / duration_ms, and echoes the id back in the response
header so a client (or a log line) can be correlated with a support report.

Dormant by default: ``main.py`` only registers the middleware when
``settings.observability_enabled`` is true.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Empty string = "no request context" (e.g. background jobs, startup).
request_id_var: ContextVar[str] = ContextVar("request_id", default="")

log = logging.getLogger("app.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, time the request, and log a structured access line."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            try:
                response: Response = await call_next(request)
            except Exception:
                dur_ms = round((time.perf_counter() - start) * 1000, 1)
                # Log with the request id, then re-raise so FastAPI's handlers run.
                log.exception(
                    "request_error",
                    extra={"method": request.method, "path": request.url.path,
                           "status": 500, "duration_ms": dur_ms},
                )
                raise
            dur_ms = round((time.perf_counter() - start) * 1000, 1)
            response.headers["X-Request-ID"] = rid
            log.info(
                "request",
                extra={"method": request.method, "path": request.url.path,
                       "status": response.status_code, "duration_ms": dur_ms},
            )
            return response
        finally:
            request_id_var.reset(token)
