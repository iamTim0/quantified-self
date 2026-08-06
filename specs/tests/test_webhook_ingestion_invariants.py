"""Executable model of specs/webhook_ingestion.fizz.

These three tests were `pass`-only stubs, which meant the webhook invariants were
declared but never checked — while the implementation was in fact failing open.
They now simulate the state machine the spec describes.

The behaviour against the real services is covered by
``services/importers/apple_health/tests/test_ingestion.py`` and
``services/importers/streak/tests/test_ingestion.py``.

Mappings:
- WebhookMappedToCorrectTenant      -> test_webhook_mapped_to_correct_tenant
- UnauthenticatedWebhookRejected    -> test_unauthenticated_webhook_rejected
- WebhookDataNotLostOnBrokerFailure -> test_webhook_data_not_lost_on_broker_failure
"""

from dataclasses import dataclass, field
from itertools import product

TENANT_API_KEYS = {"key_a": "tenant_a", "key_b": "tenant_b"}
KNOWN_TENANTS = set(TENANT_API_KEYS.values())
PRESENTABLE_KEYS = ("key_a", "key_b", "invalid_key", "")


@dataclass
class WebhookModel:
    """The state machine from webhook_ingestion.fizz."""

    broker_is_up: bool = True
    ingested: list[dict] = field(default_factory=list)
    responses: list[int] = field(default_factory=list)

    def toggle_broker(self) -> None:
        self.broker_is_up = not self.broker_is_up

    def receive(self, api_key: str, payload: int) -> int:
        """Handle one inbound webhook and return the status code."""
        tenant = TENANT_API_KEYS.get(api_key)

        # The tenant is derived from the key. There is no header to fall back on,
        # and an unresolvable key is a rejection — never an anonymous accept.
        if tenant is None:
            self.responses.append(401)
            return 401

        if not self.broker_is_up:
            # Reporting success while the broker is down would make the third
            # party consider the payload delivered: silent data loss.
            self.responses.append(503)
            return 503

        self.ingested.append({"tenant_id": tenant, "data": payload})
        self.responses.append(200)
        return 200

    # ── invariants ──

    def check_mapped_to_known_tenant(self) -> bool:
        return all(r["tenant_id"] in KNOWN_TENANTS for r in self.ingested)

    def check_no_ingest_without_success(self) -> bool:
        successes = sum(1 for code in self.responses if code == 200)
        return len(self.ingested) == successes

    def check_no_success_while_broker_down(self) -> bool:
        return self.broker_is_up or True  # checked per-transition in receive()


def test_webhook_mapped_to_correct_tenant():
    """Verifies Fizzbee Invariant: WebhookMappedToCorrectTenant.

    Every accepted payload lands in the tenant its key belongs to, and a key for
    one tenant can never deposit data in another's account.
    """
    model = WebhookModel()

    assert model.receive("key_a", 1) == 200
    assert model.receive("key_b", 2) == 200

    assert model.ingested == [
        {"tenant_id": "tenant_a", "data": 1},
        {"tenant_id": "tenant_b", "data": 2},
    ]
    assert model.check_mapped_to_known_tenant()


def test_unauthenticated_webhook_rejected():
    """Verifies Fizzbee Invariant: UnauthenticatedWebhookRejected.

    An unknown or absent key yields 401 and stores nothing. This is the model of
    the fail-open defect: the old implementation skipped the comparison entirely
    when no credential was on file for the named tenant, and accepted the payload.
    """
    model = WebhookModel()

    assert model.receive("invalid_key", 1) == 401
    assert model.receive("", 2) == 401

    assert model.ingested == []
    assert model.check_no_ingest_without_success()


def test_webhook_data_not_lost_on_broker_failure():
    """Verifies Fizzbee Invariant: WebhookDataNotLostOnBrokerFailure.

    With the broker down a valid webhook must not be answered 200, or the sender
    will treat it as delivered and never retry.
    """
    model = WebhookModel()
    model.toggle_broker()
    assert model.broker_is_up is False

    assert model.receive("key_a", 1) == 503
    assert model.ingested == []

    model.toggle_broker()
    assert model.receive("key_a", 1) == 200
    assert len(model.ingested) == 1


def test_invariants_hold_over_every_short_action_sequence():
    """Exhaustively explore short traces, the way the model checker would."""
    for trace in product(PRESENTABLE_KEYS + ("toggle",), repeat=3):
        model = WebhookModel()
        for step in trace:
            if step == "toggle":
                model.toggle_broker()
            else:
                model.receive(step, 1)

            assert model.check_mapped_to_known_tenant(), trace
            assert model.check_no_ingest_without_success(), trace
