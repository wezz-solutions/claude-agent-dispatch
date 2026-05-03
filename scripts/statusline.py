#!/usr/bin/env python3
"""
Claude Code status line script for AgentDispatch.
Reads .marker/.done sentinel files, outputs one-line dispatch status.

Receives session JSON on stdin from Claude Code.
Configure in settings.json:
  "statusLine": {
    "type": "command",
    "command": "python <path>/agent-dispatch/scripts/statusline.py",
    "refreshInterval": 3
  }
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def _find_dispatches_dir() -> Path:
    plugin_dir = Path(os.environ.get(
        "DISPATCH_PLUGIN_DIR",
        str(Path(__file__).resolve().parent.parent),
    ))

    # Try project dispatch.json for custom dispatches_dir
    cwd = Path.cwd()
    project_root = cwd
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            project_root = parent
            break

    config_path = project_root / ".claude" / "dispatch.json"
    dispatches_rel = ".claude/dispatches"
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
            dispatches_rel = cfg.get("dispatches_dir", dispatches_rel)
        except (json.JSONDecodeError, OSError):
            pass

    return project_root / dispatches_rel


def _read_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def main():
    # Read session data from stdin (Claude Code provides this)
    try:
        session = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        session = {}

    dispatches_dir = _find_dispatches_dir()
    if not dispatches_dir.exists():
        print(f"{DIM}dispatch: idle{RESET}")
        return

    # Count active dispatches
    markers = list(dispatches_dir.glob("*.marker"))
    active = []
    hanging = 0

    now = datetime.now(timezone.utc)
    for mf in markers:
        data = _read_json(mf)
        if not data:
            continue

        agent = data.get("agent", "?")
        model = data.get("model", "?")
        # Shorten model name
        short_model = model.split("-")[0] if "-" in model else model
        if "sonnet" in model:
            short_model = "son"
        elif "opus" in model:
            short_model = "opus"
        elif "haiku" in model:
            short_model = "hai"

        started = data.get("started", "")
        elapsed = 0
        if started:
            try:
                start_dt = datetime.fromisoformat(started)
                elapsed = int((now - start_dt).total_seconds())
            except (ValueError, TypeError):
                pass

        last_act = data.get("last_activity", "")
        idle = 0
        if last_act:
            try:
                act_dt = datetime.fromisoformat(last_act)
                idle = int((now - act_dt).total_seconds())
            except (ValueError, TypeError):
                pass

        entry = f"{agent}/{short_model} {elapsed}s"
        if idle > 300:
            entry += f" {RED}idle{RESET}"
            hanging += 1

        active.append(entry)

    # Sum cost from recent .done files
    total_cost = 0.0
    done_count = 0
    for df in dispatches_dir.glob("*.done"):
        data = _read_json(df)
        if data:
            cost = data.get("cost_usd")
            if cost is not None:
                total_cost += cost
            done_count += 1

    # Build status line
    parts = []

    if active:
        agent_str = " | ".join(active[:3])  # Show max 3
        if len(active) > 3:
            agent_str += f" +{len(active) - 3}"
        parts.append(f"{GREEN}{len(active)} running{RESET}: {agent_str}")
    else:
        parts.append(f"{DIM}dispatch: idle{RESET}")

    if total_cost > 0 or done_count > 0:
        parts.append(f"{YELLOW}${total_cost:.2f}{RESET} ({done_count} done)")

    if hanging > 0:
        parts.append(f"{RED}{hanging} hanging{RESET}")

    print(" | ".join(parts))


if __name__ == "__main__":
    main()
