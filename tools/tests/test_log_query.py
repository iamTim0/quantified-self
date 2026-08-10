"""Unit tests for tools.log_query."""
from tools.log_query import filter_log_line, query_logs
import tempfile
import os


def test_filter_by_req_id_match():
    line = "2026-07-26 22:10:00 [qs-core] [INFO] [req_id=req_12345] 📥 -> GET /api/v1/data/metrics"
    assert filter_log_line(line, req_id="req_12345") is True


def test_filter_by_req_id_no_match():
    line = "2026-07-26 22:10:00 [qs-core] [INFO] [req_id=req_12345] 📥 -> GET /api/v1/data/metrics"
    assert filter_log_line(line, req_id="req_99999") is False


def test_filter_by_service_match():
    line = "2026-07-26 22:10:00 [qs-core] [INFO] [req_id=req_12345] Test message"
    assert filter_log_line(line, service="qs-core") is True


def test_filter_by_service_no_match():
    line = "2026-07-26 22:10:00 [qs-core] [INFO] [req_id=req_12345] Test message"
    assert filter_log_line(line, service="qs-api-gateway") is False


def test_filter_by_level():
    line = "2026-07-26 22:10:00 [qs-core] [ERROR] [req_id=req_12345] Something failed"
    assert filter_log_line(line, level="ERROR") is True
    assert filter_log_line(line, level="INFO") is False


def test_filter_by_keyword():
    line = "2026-07-26 22:10:00 [qs-core] [INFO] [req_id=req_12345] Idempotency key collision detected"
    assert filter_log_line(line, query="idempotency") is True
    assert filter_log_line(line, query="jwt") is False


def test_filter_no_filters_matches_all():
    line = "2026-07-26 22:10:00 [qs-core] [INFO] [req_id=req_12345] Test message"
    assert filter_log_line(line) is True


def test_query_logs_returns_matching_lines():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "qs-platform.log")
        with open(log_file, "w") as f:
            f.write("2026-07-26 [qs-core] [INFO] [req_id=req_abc] Good line\n")
            f.write("2026-07-26 [qs-core] [ERROR] [req_id=req_xyz] Error line\n")
            f.write("2026-07-26 [qs-api-gateway] [INFO] [req_id=req_abc] Gateway line\n")

        results = query_logs(req_id="req_abc", log_dir=tmpdir)
        assert len(results) == 2
        assert all("req_abc" in r for r in results)
