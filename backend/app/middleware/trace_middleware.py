"""HTTP 中间件：为每个请求注入 trace_id，响应头带回 X-Trace-Id。"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.observability.trace_context import get_trace_id, new_trace_id, set_trace_id

logger = logging.getLogger("app.trace")


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("x-trace-id") or request.headers.get("X-Trace-Id")
        trace_id = (incoming or "").strip() or new_trace_id()
        set_trace_id(trace_id)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled path=%s trace=%s", request.url.path, trace_id
            )
            raise
        response.headers["X-Trace-Id"] = trace_id
        return response
