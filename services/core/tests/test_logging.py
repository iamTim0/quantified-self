import logging
import os
import pytest
from unittest.mock import patch, MagicMock


def test_setup_tracing_logger_registers_three_handlers():
    from core.tracing import setup_tracing_logger

    root = logging.getLogger()
    original_handlers = root.handlers[:]

    with patch('os.makedirs') as mock_makedirs:
        with patch('core.tracing.RotatingFileHandler') as mock_rfh:
            # Give the mock handler a real integer .level so logging callHandlers doesn't break
            mock_handler = MagicMock()
            mock_handler.level = logging.NOTSET
            mock_handler.filter.return_value = True
            mock_rfh.return_value = mock_handler

            setup_tracing_logger('test-svc')

            mock_makedirs.assert_called_once_with('logs', exist_ok=True)
            assert mock_rfh.call_count == 2  # service log + platform log
            assert len(root.handlers) == 3   # stdout + service file + platform file

            # Restore handlers INSIDE the patch context before mocks are torn down
            root.handlers = original_handlers
