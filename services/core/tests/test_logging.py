import logging
import os
import pytest
from unittest.mock import patch, MagicMock


def test_setup_tracing_logger_registers_three_handlers():
    from core.tracing import setup_tracing_logger
    import logging.handlers

    root = logging.getLogger()
    original_handlers = root.handlers[:]

    try:
        with patch('os.makedirs') as mock_makedirs:
            with patch('core.tracing.RotatingFileHandler') as mock_rfh:
                mock_handler = MagicMock()
                mock_rfh.return_value = mock_handler

                setup_tracing_logger('test-svc')

                mock_makedirs.assert_called_once_with('logs', exist_ok=True)
                assert mock_rfh.call_count == 2  # service log + platform log

                assert len(root.handlers) == 3  # stdout + service file + platform file
    finally:
        root.handlers = original_handlers
