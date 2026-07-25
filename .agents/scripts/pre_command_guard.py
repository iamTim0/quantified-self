import sys
import json

def main():
    try:
        raw_input = sys.stdin.read()
        data = json.loads(raw_input) if raw_input else {}
    except Exception:
        data = {}

    tool_call = data.get("toolCall", {})
    args = tool_call.get("args", {})
    cmd = args.get("CommandLine", "")

    # Safety Guardrail: Block dangerous operations
    forbidden = ["rm -rf /", "rmdir /s /q c:\\", "git push --force origin main", "git push -f origin main"]
    for f in forbidden:
        if f in cmd.lower():
            output = {
                "decision": "deny",
                "reason": f"Command blocked by agentic safety guardrail: contains dangerous command pattern '{f}'"
            }
            print(json.dumps(output))
            return

    print(json.dumps({"decision": "allow"}))

if __name__ == "__main__":
    main()
