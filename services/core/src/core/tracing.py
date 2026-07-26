"""Correlation ID and Request Tracing Module.

Enables end-to-end request correlation across API Gateway, Core Service,
NATS JetStream events, and Importer background workers.
"""

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Async-safe context variable for correlation ID
_current_request_id: ContextVar[str] = ContextVar("current_request_id", default="req_sys_init")


def get_current_request_id() -> str:
    """Retrieve the active X-Request-ID correlation ID."""
    return _current_request_id.get()


def set_current_request_id(request_id: str) -> None:
    """Set the X-Request-ID correlation ID for the current context."""
    _current_request_id.set(request_id)


class CorrelationLogFilter(logging.Filter):
    """Logging filter that injects [request_id] into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_current_request_id()
        return True


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Starlette middleware to extract or generate X-Request-ID headers."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = f"req_{uuid.uuid4().hex[:12]}"

        token = _current_request_id.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            _current_request_id.reset(token)


def setup_tracing_logger(service_name: str):
    """Configure root logger format with correlation ID prefix."""
    log_format = f"%(asctime)s [{service_name}] [%(levelname)s] [req_id=%(request_id)s] %(message)s"
    formatter = logging.Formatter(log_format)

    handler = logging.StreamHandler()
    handler.addFilter(CorrelationLogFilter())
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)
