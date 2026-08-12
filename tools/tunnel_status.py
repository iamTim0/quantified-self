"""Cloudflare Quick Tunnel Status & URL Extractor for Quantified Self.

Queries docker logs for the `qs-cloudflared-tunnel` / `cloudflared` container service
and displays the generated `trycloudflare.com` public HTTPS URL and API endpoints.

Usage:
    python -m tools.tunnel_status
"""

import os
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
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)  # noqa: PLW1510
        return res.stdout + "\n" + res.stderr
    except Exception as e:  # noqa: BLE001
        return f"Error fetching docker logs: {e}"


def main():
    print("Checking Cloudflare Tunnel status...")
    logs = get_container_logs()

    # Check if TUNNEL_TOKEN environment variable is configured or container registered connection
    tunnel_token = os.getenv("TUNNEL_TOKEN", "")
    if not tunnel_token and os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("TUNNEL_TOKEN="):
                    tunnel_token = line.split("=", 1)[1].strip()
                    break

    is_named_tunnel = bool(tunnel_token) or "Starting Named Cloudflare Tunnel" in logs or "Registered tunnel connection" in logs or "Starting tunnel" in logs

    if is_named_tunnel:
        # From the environment: the tunnel's hostname belongs to whoever runs it.
        domain = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or "https://<your-tunnel-host>"
        print("\n======================================================================")
        print("  NAMED CLOUDFLARE TUNNEL IS ACTIVE!")
        print("======================================================================")
        print(f"  Public Base Domain:      {domain}")
        print(f"  Streak 2.0 Webhook:      {domain}/api/v1/ingest/streak")
        print(f"  Apple Health Webhook:    {domain}/api/v1/ingest/apple-health")
        print(f"  API Gateway Health:      {domain}/health")
        print(f"  Data Points API:         {domain}/api/v1/data/points")
        print("======================================================================\n")
        return

    url = find_tunnel_url(logs)

    if not url:
        print("\n[WARN] Cloudflare Tunnel URL or active status not found in container logs.", file=sys.stderr)
        print("Ensure the tunnel container is started by running:", file=sys.stderr)
        print("  task dev:tunnel", file=sys.stderr)
        print("  OR: docker compose -f infra/docker-compose.yml up -d cloudflared\n", file=sys.stderr)
        sys.exit(1)

    print("\n======================================================================")
    print("  CLOUDFLARE QUICK TUNNEL IS ACTIVE!")
    print("======================================================================")
    print(f"  Public Base URL:         {url}")
    print(f"  Streak 2.0 Webhook:      {url}/api/v1/ingest/streak")
    print(f"  Apple Health Webhook:    {url}/api/v1/ingest/apple-health")
    print(f"  API Gateway Health:      {url}/health")
    print(f"  Data Points API:         {url}/api/v1/data/points")
    print("======================================================================\n")


if __name__ == "__main__":
    main()
