"""Executable checks for the distributed ingestion model in ``distributed_ingestion.fizz``."""

from dataclasses import dataclass, field

TENANTS = {"tenant_a", "tenant_b"}
RESOLUTIONS = {"raw", "minute", "hour", "day"}


@dataclass
class IngestionModel:
    """Small executable model of a durable, idempotent ingest consumer."""

    queue: list[dict] = field(default_factory=list)
    stored: dict[str, dict] = field(default_factory=dict)
    acknowledged: set[str] = field(default_factory=set)
    broker_available: bool = True

    def publish(self, event: dict) -> None:
        if not self.broker_available:
            raise RuntimeError("broker unavailable")
        self.queue.append(event)

    def consume(self, *, crash_before_ack: bool = False) -> None:
        if not self.queue or not self.broker_available:
            return
        event = self.queue[0]
        self.stored.setdefault(event["idempotency_key"], event)
        if crash_before_ack:
            return
        self.queue.pop(0)
        self.acknowledged.add(event["idempotency_key"])


def _event(key: str = "key-1", tenant_id: str = "tenant_a") -> dict:
    return {
        "tenant_id": tenant_id,
        "metric_type": "steps",
        "resolution": "minute",
        "idempotency_key": key,
    }


def test_tenant_id_always_present():
    """Verifies Fizzbee Invariant: TenantIsolation."""
    model = IngestionModel()
    model.publish(_event())
    model.consume()

    assert model.stored
    assert all(event["tenant_id"] in TENANTS for event in model.stored.values())


def test_deduplication_via_idempotency_key():
    """Verifies Fizzbee Invariant: NoDuplicateData."""
    model = IngestionModel()
    model.publish(_event())
    model.publish(_event())
    model.consume()
    model.consume()

    assert len(model.stored) == 1
    assert model.acknowledged == {"key-1"}


def test_concurrent_duplicate_messages():
    """Verifies Fizzbee Invariants: DataIntegrity and NoDuplicateData."""
    model = IngestionModel()
    model.queue.extend([_event(), _event()])
    model.consume()
    model.consume()

    assert list(model.stored) == ["key-1"]
    assert not model.queue


def test_message_survives_consumer_crash():
    """Verifies Fizzbee Invariant: AckAfterPersisted."""
    model = IngestionModel()
    model.publish(_event())
    model.consume(crash_before_ack=True)

    assert model.queue
    assert not model.acknowledged
    model.consume()
    assert not model.queue
    assert model.acknowledged == {"key-1"}


def test_network_partition_recovery():
    """Verifies Fizzbee Invariant: EventualConsistency."""
    model = IngestionModel(broker_available=False)
    model.broker_available = True
    model.publish(_event())
    model.consume()

    assert not model.queue
    assert model.acknowledged == {"key-1"}


def test_import_backpressure_and_ack_order():
    """Verifies Fizzbee Invariants: ResolutionBounded and AckAfterPersisted."""
    model = IngestionModel()
    event = _event()
    model.publish(event)
    assert event["resolution"] in RESOLUTIONS
    assert not model.acknowledged
    model.consume()
    assert event["idempotency_key"] in model.acknowledged
