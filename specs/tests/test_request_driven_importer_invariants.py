"""Executable checks for the request-driven importer model."""


def dispatch(
    *,
    source_type: str,
    in_flight: set[str],
    source_id: str,
    task_subject: str,
    config: dict[str, object],
) -> tuple[int, str | None, dict[str, object]]:
    """Model Core's single-flight task gate and importer task contract."""
    if source_id in in_flight:
        return 409, None, {}
    expected_subject = f"qs.task.sync.{source_type}"
    if task_subject != expected_subject:
        return 422, None, {}
    if not config.get("tenant_id") or not config.get("request_id"):
        return 422, None, {}
    in_flight.add(source_id)
    return 202, expected_subject, config


def test_importer_standard_invariants():
    """Verifies Fizzbee Invariant: RequestDrivenImporter."""
    in_flight: set[str] = set()
    config = {"tenant_id": "tenant_a", "request_id": "req-1", "window_hours": 1}

    status, subject, received = dispatch(
        source_type="apple_health",
        in_flight=in_flight,
        source_id="source-1",
        task_subject="qs.task.sync.apple_health",
        config=config,
    )
    assert status == 202
    assert subject == "qs.task.sync.apple_health"
    assert received == config

    duplicate, _, _ = dispatch(
        source_type="apple_health",
        in_flight=in_flight,
        source_id="source-1",
        task_subject="qs.task.sync.apple_health",
        config=config,
    )
    assert duplicate == 409


def test_importer_rejects_wrong_subject_and_missing_correlation():
    """Verifies Fizzbee Invariants: RequestDrivenImporter and CorrelationIdPropagated."""
    status, _, _ = dispatch(
        source_type="whoop",
        in_flight=set(),
        source_id="source-1",
        task_subject="qs.task.sync.apple_health",
        config={"tenant_id": "tenant_a", "request_id": "req-1"},
    )
    assert status == 422

    status, _, _ = dispatch(
        source_type="whoop",
        in_flight=set(),
        source_id="source-1",
        task_subject="qs.task.sync.whoop",
        config={"tenant_id": "tenant_a"},
    )
    assert status == 422
