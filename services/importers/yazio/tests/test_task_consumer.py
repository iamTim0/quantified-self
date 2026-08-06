"""Unit tests for Yazio NATS Task Consumer & Coordination.

Verifies:
- Concurrency locking per tenant.
- Idle behavior when no connector token is configured.
- NATS task message acknowledgement.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from yazio_importer.main import active_syncs, process_task_message


@pytest.mark.asyncio
async def test_process_task_message_concurrency_lock():
    """Verifies that concurrent sync tasks for the same tenant are safely locked."""
    msg = AsyncMock()
    msg.data = json.dumps({"tenant_id": "tenant_locked"}).encode("utf-8")
    nc = AsyncMock()

    active_syncs.add("tenant_locked")
    try:
        await process_task_message(msg, nc)
        msg.ack.assert_called_once()
    finally:
        active_syncs.discard("tenant_locked")


@pytest.mark.asyncio
async def test_process_task_message_no_token():
    """Verifies idle behavior when no active connector token is found in Core Service."""
    msg = AsyncMock()
    msg.data = json.dumps({"tenant_id": "tenant_no_token"}).encode("utf-8")
    nc = AsyncMock()

    with patch("yazio_importer.main.get_connector_token_from_core", return_value=(None, None, None)):
        await process_task_message(msg, nc)
        msg.ack.assert_called_once()


@pytest.mark.asyncio
async def test_process_task_message_missing_tenant_id():
    """Verifies missing tenant_id in payload is safely acknowledged and discarded."""
    msg = AsyncMock()
    msg.data = json.dumps({}).encode("utf-8")
    nc = AsyncMock()

    await process_task_message(msg, nc)
    msg.ack.assert_called_once()
