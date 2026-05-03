"""
PreToolUse hook: intercepts native Agent tool calls and redirects to mcp__dispatch__run.
Only active when dispatch.json -> enforce_dispatch: true.
Dispatched sessions (DISPATCH_DEPTH > 0) are allowed through.
"""

import json
import os
import sys
from pathlib import Path


def _load_dispatch_config() -> dict:
    """Load dispatch.json with project -> user -> defaults resolution."""
    plugin_dir = Path(os.environ.get(
        "DISPATCH_PLUGIN_DIR",
        str(Path(__file__).resolve().parent.parent),
    ))

    defaults_path = plugin_dir / "config" / "defaults.json"
    user_path = Path.home() / ".claude" / "dispatch.json"

    cwd = Path.cwd()
    project_root = cwd
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            project_root = parent
            break
    project_path = project_root / ".claude" / "dispatch.json"

    config = {}
    for path in [defaults_path, user_path, project_path]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                config.update(data)
            except (json.JSONDecodeError, OSError):
                pass
    return config


def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"decision": "allow"}))
        return

    tool_name = event.get("tool_name", "")

    if tool_name != "Agent":
        print(json.dumps({"decision": "allow"}))
        return

    # Allow if inside a dispatched session
    depth = int(os.environ.get("DISPATCH_DEPTH", "0"))
    if depth > 0:
        print(json.dumps({"decision": "allow"}))
        return

    # Check if enforcement is enabled
    config = _load_dispatch_config()
    if not config.get("enforce_dispatch", False):
        print(json.dumps({"decision": "allow"}))
        return

    # Extract original params for translation hint
    params = event.get("tool_input", {})
    prompt_preview = (params.get("prompt", "") or "")[:100]
    model = params.get("model", "")
    agent_type = params.get("subagent_type", "")

    agent_hint = agent_type if agent_type else "general"
    model_hint = model if model else "(config default)"

    reason = (
        f"BLOCKED: Use mcp__dispatch__run instead of native Agent tool.\n\n"
        f"Translate your call to:\n"
        f"  mcp__dispatch__run(\n"
        f'    query="<short 20 char label>",\n'
        f'    prompt="<your full task prompt>",\n'
        f'    agent="{agent_hint}",\n'
        f'    model="{model_hint}"\n'
        f"  )\n\n"
        f"Original prompt preview: {prompt_preview}..."
    )

    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
