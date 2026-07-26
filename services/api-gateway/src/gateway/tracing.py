"""Correlation ID and Request Tracing Module for API Gateway.

Injects and propagates X-Request-ID across all downstream proxies.
"""

import logging
import os
import time
import uuid
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_current_request_id: ContextVar[str] = ContextVar("current_request_id", default="req_sys_init")


def get_current_request_id() -> str:
    return _current_request_id.get()


def set_current_request_id(request_id: str) -> None:
    _current_request_id.set(request_id)


class CorrelationLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_current_request_id()
        return True


class RequestTracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = f"req_{uuid.uuid4().hex[:12]}"

        token = _current_request_id.set(request_id)
        start_time = time.perf_counter()
        
        path = request.url.path
        is_health = path == "/health"

        if not is_health:
            logging.getLogger("api-gateway").info(
                f"📥 -> {request.method} {path}"
            )

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id

            if not is_health:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logging.getLogger("api-gateway").info(
                    f"📤 <- {request.method} {path} - {response.status_code} ({duration_ms:.2f}ms)"
                )
            return response
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logging.getLogger("api-gateway").error(
                f"❌ <- {request.method} {path} - Failed: {e} ({duration_ms:.2f}ms)"
            )
            raise
        finally:
            _current_request_id.reset(token)


def setup_tracing_logger(service_name: str):
    """Configure root logger format with correlation ID prefix.

    Registers three handlers on the root logger:
    - stdout StreamHandler for live console output
    - RotatingFileHandler for service-specific log file (logs/{service_name}.log)
    - RotatingFileHandler for aggregated platform log (logs/qs-platform.log)

    All handlers inject the correlation request_id via CorrelationLogFilter.
    Logs are always written to the project root logs/ directory.
    """
    # Resolve project root: services/api-gateway/src/gateway/tracing.py -> 4 levels up
    _log_dir = Path(__file__).resolve().parents[4] / "logs"
    _log_dir.mkdir(exist_ok=True)

    log_format = f"%(asctime)s [{service_name}] [%(levelname)s] [req_id=%(request_id)s] %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    stdout_handler = logging.StreamHandler()
    stdout_handler.addFilter(CorrelationLogFilter())
    stdout_handler.setFormatter(formatter)

    service_handler = RotatingFileHandler(
        _log_dir / f'{service_name}.log', maxBytes=10 * 1024 * 1024, backupCount=5
    )
    service_handler.addFilter(CorrelationLogFilter())
    service_handler.setFormatter(formatter)

    platform_handler = RotatingFileHandler(
        _log_dir / 'qs-platform.log', maxBytes=10 * 1024 * 1024, backupCount=5
    )
    platform_handler.addFilter(CorrelationLogFilter())
    platform_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [stdout_handler, service_handler, platform_handler]
    root_logger.setLevel(logging.INFO)
