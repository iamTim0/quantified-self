import json
from unittest.mock import AsyncMock, patch

import pytest
from yazio_importer.main import active_syncs, process_task_message


@pytest.mark.asyncio
async def test_process_task_message_concurrency_lock():
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
    msg = AsyncMock()
    msg.data = json.dumps({"tenant_id": "tenant_no_token"}).encode("utf-8")
    nc = AsyncMock()

    with patch("yazio_importer.main.get_connector_token_from_core", return_value=(None, None)):
        await process_task_message(msg, nc)
        msg.ack.assert_called_once()
