"""Unit tests for Core Data Service Tenant Context and Async Scope.

Verifies the Fizzbee TenantIsolation invariant in Python application code.
"""

import asyncio

import pytest
from core.db.tenant import (
    _current_tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
)


def test_tenant_context_default_raises_runtime_error():
    """Verify that accessing tenant_id without setting it raises RuntimeError.
    
    Fizzbee Invariant: TenantIsolation
    """
    token = _current_tenant_id.set(None)
    try:
        with pytest.raises(RuntimeError, match="tenant_id not set in context"):
            get_current_tenant_id()
    finally:
        _current_tenant_id.reset(token)

def test_tenant_context_set_and_get():
    """Verify contextvar set and get behavior within same coroutine scope."""
    token = _current_tenant_id.set("tenant-uuid-1234")
    try:
        assert get_current_tenant_id() == "tenant-uuid-1234"
    finally:
        _current_tenant_id.reset(token)

@pytest.mark.asyncio
async def test_tenant_context_async_concurrency_isolation():
    """Verify that concurrent async tasks maintain isolated tenant_ids.
    
    Fizzbee Invariant: TenantIsolation (under concurrent request load)
    """
    results = {}

    async def worker(tenant_id: str, delay: float):
        set_current_tenant_id(tenant_id)
        await asyncio.sleep(delay)
        # Verify tenant_id remained untouched by other concurrent tasks
        results[tenant_id] = get_current_tenant_id()

    await asyncio.gather(
        worker("tenant-A", 0.05),
        worker("tenant-B", 0.02),
        worker("tenant-C", 0.01),
    )

    assert results["tenant-A"] == "tenant-A"
    assert results["tenant-B"] == "tenant-B"
    assert results["tenant-C"] == "tenant-C"
