from __future__ import annotations

import json
import sys
from typing import Any


def _read_input() -> dict[str, Any]:
    try:
        raw_input = sys.stdin.read()
        payload = json.loads(raw_input) if raw_input else {}
    except (json.JSONDecodeError, OSError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _extract_command(payload: dict[str, Any]) -> tuple[str, bool]:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        command = tool_input.get("command")
        if isinstance(command, str):
            return command, True

    tool_call = payload.get("toolCall")
    if isinstance(tool_call, dict):
        args = tool_call.get("args")
        if isinstance(args, dict):
            command = args.get("CommandLine")
            if isinstance(command, str):
                return command, False

    return "", payload.get("hook_event_name") == "PreToolUse"


def main() -> None:
    payload = _read_input()
    command, is_codex = _extract_command(payload)
    forbidden = [
        "rm -rf /",
        "rmdir /s /q c:\\",
        "git push --force origin main",
        "git push -f origin main",
    ]

    for pattern in forbidden:
        if pattern in command.casefold():
            reason = (
                "Command blocked by agentic safety guardrail: "
                f"contains dangerous command pattern '{pattern}'"
            )
            if is_codex:
                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            else:
                output = {"decision": "deny", "reason": reason}
            print(json.dumps(output))
            return

    print(json.dumps({} if is_codex else {"decision": "allow"}))


if __name__ == "__main__":
    main()
