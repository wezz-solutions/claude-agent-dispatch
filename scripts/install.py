"""
AgentDispatch installer.
Registers MCP server, creates default config, optionally adds hooks.

Usage:
    python install.py                  # Project-level install
    python install.py --user           # User-level install
    python install.py --enforce        # Also add Agent-intercept hook
    python install.py --uninstall      # Remove MCP registration and hooks
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
SERVER_SCRIPT = PLUGIN_DIR / "scripts" / "server.py"
HOOK_SCRIPT = PLUGIN_DIR / "hooks" / "intercept-agent.py"
DEFAULTS_PATH = PLUGIN_DIR / "config" / "defaults.json"


def _find_project_root() -> Path:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return cwd


def _load_json(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _check_backend(name: str, cmd: str) -> str:
    found = shutil.which(cmd)
    if found:
        return f"  {name}: FOUND ({found})"
    return f"  {name}: NOT FOUND — install required for {name} models"


def install(scope: str, enforce: bool):
    project_root = _find_project_root()
    is_user = scope == "user"

    print(f"AgentDispatch installer")
    print(f"  Plugin dir: {PLUGIN_DIR}")
    print(f"  Scope: {'user (~/.claude/)' if is_user else f'project ({project_root})'}")
    print()

    # ── 1. Register MCP server ────────────────────────────
    if is_user:
        mcp_path = Path.home() / ".claude" / "mcp.json"
    else:
        mcp_path = project_root / ".mcp.json"

    mcp_config = _load_json(mcp_path)

    server_path = str(SERVER_SCRIPT).replace("\\", "/")
    plugin_path = str(PLUGIN_DIR).replace("\\", "/")

    server_entry = {
        "command": "python",
        "args": [server_path],
        "env": {
            "DISPATCH_PLUGIN_DIR": plugin_path,
        },
    }

    if "mcpServers" in mcp_config:
        mcp_config["mcpServers"]["dispatch"] = server_entry
    else:
        mcp_config["dispatch"] = server_entry

    _save_json(mcp_path, mcp_config)
    print(f"  MCP server registered in {mcp_path}")

    # ── 2. Create dispatch.json config ────────────────────
    if is_user:
        config_path = Path.home() / ".claude" / "dispatch.json"
    else:
        config_path = project_root / ".claude" / "dispatch.json"

    if config_path.exists():
        print(f"  Config already exists: {config_path} (kept)")
    else:
        defaults = _load_json(DEFAULTS_PATH)
        _save_json(config_path, defaults)
        print(f"  Default config created: {config_path}")

    # ── 3. Add hooks (if --enforce) ───────────────────────
    if enforce:
        if is_user:
            settings_path = Path.home() / ".claude" / "settings.json"
        else:
            settings_path = project_root / ".claude" / "settings.json"

        settings = _load_json(settings_path)
        hooks = settings.setdefault("hooks", {})
        pre_tool = hooks.setdefault("PreToolUse", [])

        hook_cmd = f"python {str(HOOK_SCRIPT).replace(chr(92), '/')}"

        already = any(
            hook_cmd in json.dumps(h)
            for h in pre_tool if isinstance(h, dict)
        )

        if already:
            print(f"  Hook already registered in {settings_path}")
        else:
            pre_tool.append({
                "matcher": "Agent",
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_cmd,
                        "timeout": 5000,
                    }
                ],
            })
            _save_json(settings_path, settings)
            print(f"  Agent-intercept hook added to {settings_path}")

    # ── 4. Configure status line ─────────────────────────
    if is_user:
        settings_path_sl = Path.home() / ".claude" / "settings.json"
    else:
        settings_path_sl = project_root / ".claude" / "settings.json"

    settings_sl = _load_json(settings_path_sl)
    statusline_script = str(PLUGIN_DIR / "scripts" / "statusline.py").replace("\\", "/")
    statusline_cmd = f"python {statusline_script}"

    existing_sl = settings_sl.get("statusLine", {})
    if isinstance(existing_sl, dict) and existing_sl.get("command") == statusline_cmd:
        print(f"  Status line already configured")
    else:
        settings_sl["statusLine"] = {
            "type": "command",
            "command": statusline_cmd,
            "refreshInterval": 3,
        }
        _save_json(settings_path_sl, settings_sl)
        print(f"  Status line configured in {settings_path_sl}")

    # ── 5. Validate backends ──────────────────────────────
    print()
    print("Backend availability:")
    print(_check_backend("claude-cli", "claude"))
    print(_check_backend("opencode", "opencode"))

    # ── 6. Summary ────────────────────────────────────────
    print()
    print("Installation complete.")
    print()
    print("Next steps:")
    print("  1. Restart Claude Code to load MCP server")
    print("  2. Edit dispatch.json to customize models/providers")
    if not enforce:
        print("  3. Run with --enforce to add Agent-intercept hook")
    print()
    print("Test: ask Claude to call mcp__dispatch__config")


def uninstall(scope: str):
    project_root = _find_project_root()
    is_user = scope == "user"

    # Remove MCP registration
    if is_user:
        mcp_path = Path.home() / ".claude" / "mcp.json"
    else:
        mcp_path = project_root / ".mcp.json"

    mcp_config = _load_json(mcp_path)
    removed = False
    if "mcpServers" in mcp_config and "dispatch" in mcp_config["mcpServers"]:
        del mcp_config["mcpServers"]["dispatch"]
        removed = True
    elif "dispatch" in mcp_config:
        del mcp_config["dispatch"]
        removed = True

    if removed:
        _save_json(mcp_path, mcp_config)
        print(f"  MCP server removed from {mcp_path}")
    else:
        print(f"  MCP server not found in {mcp_path}")

    # Remove hooks
    if is_user:
        settings_path = Path.home() / ".claude" / "settings.json"
    else:
        settings_path = project_root / ".claude" / "settings.json"

    settings = _load_json(settings_path)
    hooks = settings.get("hooks", {})
    pre_tool = hooks.get("PreToolUse", [])

    hook_script_str = str(HOOK_SCRIPT).replace("\\", "/")
    original_len = len(pre_tool)
    pre_tool = [h for h in pre_tool if hook_script_str not in json.dumps(h)]

    if len(pre_tool) < original_len:
        hooks["PreToolUse"] = pre_tool
        _save_json(settings_path, settings)
        print(f"  Hook removed from {settings_path}")
    else:
        print(f"  No hook found in {settings_path}")

    print()
    print("Uninstall complete. Restart Claude Code to take effect.")


def main():
    parser = argparse.ArgumentParser(description="AgentDispatch installer")
    parser.add_argument("--user", action="store_true", help="Install at user level (~/.claude/)")
    parser.add_argument("--enforce", action="store_true", help="Add Agent-intercept hook")
    parser.add_argument("--uninstall", action="store_true", help="Remove MCP and hooks")
    args = parser.parse_args()

    scope = "user" if args.user else "project"

    if args.uninstall:
        uninstall(scope)
    else:
        install(scope, args.enforce)


if __name__ == "__main__":
    main()
