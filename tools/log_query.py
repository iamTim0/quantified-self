"""High-speed structured log query CLI for the Quantified Self Platform.

Allows agents and developers to filter across logs/ by correlation ID,
service name, log level, or keyword query.

Usage:
    python -m tools.log_query --req-id req_abc123
    python -m tools.log_query --service qs-core --level ERROR
    python -m tools.log_query --query "idempotency" --limit 50
    python -m tools.log_query --service qs-platform --tail 100
"""

import argparse
import glob
import os
import sys
from pathlib import Path


def filter_log_line(
    line: str,
    req_id: str | None = None,
    service: str | None = None,
    level: str | None = None,
    query: str | None = None,
) -> bool:
    """Return True if the log line matches all provided filters."""
    if req_id and f"[req_id={req_id}]" not in line:
        return False
    if service and f"[{service}]" not in line:
        return False
    if level and f"[{level.upper()}]" not in line:
        return False
    if query and query.lower() not in line.lower():
        return False
    return True


def query_logs(
    req_id: str | None = None,
    service: str | None = None,
    level: str | None = None,
    query: str | None = None,
    limit: int = 100,
    tail: int | None = None,
    log_dir: str = "logs",
) -> list[str]:
    """Search log files and return matched lines."""
    # If service specified, target that file; else search platform log or all logs
    if service:
        # Try exact service file first, then platform log
        candidates = [
            os.path.join(log_dir, f"{service}.log"),
            os.path.join(log_dir, "qs-platform.log"),
        ]
    else:
        candidates = sorted(glob.glob(os.path.join(log_dir, "*.log")))

    results = []
    for file_path in candidates:
        if not os.path.exists(file_path):
            continue
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if tail:
                lines = lines[-tail:]
            for line in lines:
                if filter_log_line(line, req_id=req_id, service=service, level=level, query=query):
                    results.append(line)
                    if len(results) >= limit:
                        return results
        except OSError:
            continue
    return results


def main():
    parser = argparse.ArgumentParser(
        description="High-Speed Log Query Tool for Quantified Self Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python -m tools.log_query --req-id req_abc123
  python -m tools.log_query --service qs-core --level ERROR
  python -m tools.log_query --query idempotency --limit 50
  python -m tools.log_query --tail 100""",
    )
    parser.add_argument("--req-id", help="Filter by X-Request-ID correlation ID (e.g. req_abc123)")
    parser.add_argument("--service", help="Filter by service label (e.g. qs-core, qs-api-gateway, qs-importer-oura)")
    parser.add_argument("--level", help="Filter by log level: INFO, WARNING, ERROR")
    parser.add_argument("--query", "-q", help="Keyword/phrase search across log lines")
    parser.add_argument("--limit", type=int, default=100, help="Max number of matching lines to return (default: 100)")
    parser.add_argument("--tail", type=int, help="Read only the last N lines from each log file before filtering")
    parser.add_argument("--log-dir", default="logs", help="Directory containing log files (default: logs/)")
    args = parser.parse_args()

    if not os.path.isdir(args.log_dir):
        print(f"[log_query] Log directory '{args.log_dir}' not found. Has the platform been started?", file=sys.stderr)
        sys.exit(1)

    results = query_logs(
        req_id=args.req_id,
        service=args.service,
        level=args.level,
        query=args.query,
        limit=args.limit,
        tail=args.tail,
        log_dir=args.log_dir,
    )

    if not results:
        print("[log_query] No matching log entries found.", file=sys.stderr)
        return

    for line in results:
        sys.stdout.write(line)


if __name__ == "__main__":
    main()
