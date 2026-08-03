"""Unit tests for Cloudflare Quick Tunnel status helper tool."""

from tools.tunnel_status import find_tunnel_url


def test_find_tunnel_url_success():
    """Verifies regex extraction of trycloudflare.com URL from container logs."""
    sample_log = """
    2026-08-03T22:58:00Z INF +-----------------------------------------------------------------------------------+
    2026-08-03T22:58:00Z INF | Your quick Tunnel has been created! Visit it at:                                  |
    2026-08-03T22:58:00Z INF | https://random-slug-1234.trycloudflare.com                                       |
    2026-08-03T22:58:00Z INF +-----------------------------------------------------------------------------------+
    """
    url = find_tunnel_url(sample_log)
    assert url == "https://random-slug-1234.trycloudflare.com"


def test_find_tunnel_url_none():
    """Verifies None returned when trycloudflare URL is missing."""
    assert find_tunnel_url("Starting container...") is None
