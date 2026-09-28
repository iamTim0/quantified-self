"""Keep a JetStream sync task leased while a pull importer works on it."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Protocol

from shared_schemas.core_status import CoreStatusUnavailable

logger = logging.getLogger(__name__)


class TaskMessage(Protocol):
    async def in_progress(self) -> None: ...

    async def ack(self) -> None: ...


def should_ack_task(*, deferred: bool = False) -> bool:
    """Keep a task open when its Core result callback failed or it was deferred."""
    return not deferred and not isinstance(sys.exc_info()[1], CoreStatusUnavailable)


def start_task_heartbeat(
    message: TaskMessage, request_id: str, *, interval_seconds: float = 10.0
) -> asyncio.Task[None]:
    """Renew the delivery deadline until the caller settles the message."""

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await message.in_progress()
            except Exception as exc:  # noqa: BLE001 - a broker outage can clear on retry
                logger.warning(
                    "[req_id=%s] Could not renew sync task lease (%s)",
                    request_id,
                    type(exc).__name__,
                )

    return asyncio.create_task(heartbeat())


async def finish_task_delivery(
    message: TaskMessage,
    heartbeat: asyncio.Task[None] | None,
    *,
    acknowledge: bool = True,
) -> None:
    """Stop renewing; leave a cancelled import available for redelivery."""
    if heartbeat is not None:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass

    current = asyncio.current_task()
    if acknowledge and (current is None or not current.cancelling()):
        await message.ack()
