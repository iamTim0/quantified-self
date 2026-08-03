"""Cloudflare Quick Tunnel Status & URL Extractor for Quantified Self.

Queries docker logs for the `qs-cloudflared-tunnel` / `cloudflared` container service
and displays the generated `trycloudflare.com` public HTTPS URL and API endpoints.

Usage:
    python -m tools.tunnel_status
"""

import re
import subprocess
import sys


def find_tunnel_url(log_output: str) -> str | None:
    """Extract trycloudflare.com URL from container log output."""
    pattern = r"https://[a-zA-Z0-9-]+\.trycloudflare\.com"
    matches = re.findall(pattern, log_output)
    if matches:
        return matches[-1]  # Return latest matched URL
    return None


def get_container_logs() -> str:
    """Fetch recent logs from cloudflared container via docker compose."""
    cmd = ["docker", "compose", "-f", "infra/docker-compose.yml", "logs", "--tail=100", "cloudflared"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return res.stdout + "\n" + res.stderr
    except Exception as e:
        return f"Error fetching docker logs: {e}"


def main():
    print("Checking Cloudflare Quick Tunnel status...")
    logs = get_container_logs()
    url = find_tunnel_url(logs)

    if not url:
        print("\n[WARN] Cloudflare Quick Tunnel URL not found in container logs.", file=sys.stderr)
        print("Ensure the tunnel container is started by running:", file=sys.stderr)
        print("  task dev:tunnel", file=sys.stderr)
        print("  OR: docker compose -f infra/docker-compose.yml up -d cloudflared\n", file=sys.stderr)
        sys.exit(1)

    print("\n======================================================================")
    print("  CLOUDFLARE QUICK TUNNEL IS ACTIVE!")
    print("======================================================================")
    print(f"  Public Base URL:         {url}")
    print(f"  Apple Health Webhook:    {url}/api/v1/ingest/apple-health")
    print(f"  API Gateway Health:      {url}/health")
    print(f"  Data Points API:         {url}/api/v1/data/points")
    print("======================================================================\n")


if __name__ == "__main__":
    main()
