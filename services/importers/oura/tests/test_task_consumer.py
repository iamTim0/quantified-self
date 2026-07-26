import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from oura_importer.main import active_syncs, process_task_message

@pytest.fixture(autouse=True)
def reset_active_syncs():
    active_syncs.clear()

@pytest.mark.asyncio
async def test_in_flight_lock_skips_concurrent_sync(caplog):
    caplog.set_level(logging.INFO)
    tenant_id = "tenant-123"
    active_syncs.add(tenant_id)

    msg = AsyncMock()
    msg.data = json.dumps({"tenant_id": tenant_id}).encode("utf-8")
    nc = AsyncMock()

    await process_task_message(msg, nc)

    msg.ack.assert_awaited_once()
    assert "Sync already in progress for tenant, skipping duplicate task" in caplog.text

@pytest.mark.asyncio
@patch("oura_importer.main.get_connector_token_from_core")
@patch("oura_importer.main.fetch_and_publish")
async def test_task_execution_uses_custom_config(mock_fetch, mock_get_token):
    tenant_id = "tenant-123"
    mock_get_token.return_value = ("fake_token", {"lookback_days": 14})
    
    msg = AsyncMock()
    msg.data = json.dumps({"tenant_id": tenant_id}).encode("utf-8")
    nc = AsyncMock()

    await process_task_message(msg, nc)

    mock_get_token.assert_awaited_once_with(tenant_id)
    mock_fetch.assert_awaited_once_with(nc, tenant_id, "fake_token", 14)
    msg.ack.assert_awaited_once()
    assert tenant_id not in active_syncs
