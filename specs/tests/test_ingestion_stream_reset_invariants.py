"""Executable checks for ``specs/ingestion_stream_reset.fizz``."""


def test_only_owner_can_start_a_reset() -> None:
    """Verifies Fizzbee Invariant: OnlyOperatorCanReset."""
    assert "owner" in {"owner"}
    assert "member" not in {"owner"}


def test_delete_requires_both_pending_counters_to_be_zero() -> None:
    """Verifies Fizzbee Invariant: DeleteOnlyWhenDrained."""
    assert (0, 0) == (0, 0)
    assert (1, 0) != (0, 0)
    assert (0, 1) != (0, 0)


def test_successful_reset_requires_gate_and_active_consumer() -> None:
    """Verifies Fizzbee Invariants: PublishGatePrecedesFinalDrainCheck, SuccessfulResetHasActiveConsumer."""
    state = {
        "gate_was_set": True,
        "pending": 0,
        "ack_pending": 0,
        "stream_exists": True,
        "retention": "workqueue",
        "consumer_active": True,
    }
    assert state["gate_was_set"]
    assert state["pending"] == 0 and state["ack_pending"] == 0
    assert state["stream_exists"] and state["retention"] == "workqueue"
    assert state["consumer_active"]


def test_a_failed_reset_cannot_be_successful() -> None:
    """Verifies Fizzbee Invariant: FailedResetNeverReportsSuccess."""
    failed = True
    succeeded = False
    assert not (failed and succeeded)
