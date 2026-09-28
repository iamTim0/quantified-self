"""Bounded retries for an importer's existing Core status callback."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

logger = logging.getLogger(__name__)


class CoreStatusUnavailable(Exception):
    """Core could not accept a sync result after transient retries."""


class StatusResponse(Protocol):
    status_code: int


async def post_status_with_retry(
    send: Callable[[], Awaitable[StatusResponse]], request_id: str
) -> bool:
    """Retry transport failures and transient responses, never permanent 4xx."""
    for attempt in range(3):
        try:
            response = await send()
        except Exception as exc:  # noqa: BLE001 - provider clients vary by service
            failure = type(exc).__name__
        else:
            status = response.status_code
            if 200 <= status < 300:
                return True
            failure = f"HTTP {status}"
            if 400 <= status < 500 and status != 429:
                logger.warning(
                    "[req_id=%s] Core rejected sync status (%s)", request_id, failure
                )
                return False

        if attempt < 2:
            await asyncio.sleep(2**attempt)

    logger.warning(
        "[req_id=%s] Could not report sync status to Core after 3 attempts (%s)",
        request_id,
        failure,
    )
    raise CoreStatusUnavailable(failure)
