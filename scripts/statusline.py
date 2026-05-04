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
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
WHITE = "\033[97m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _find_dispatches_dir(session_id: str = "") -> Path:
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

    base = project_root / dispatches_rel
    if session_id:
        return base / session_id
    return base


def _read_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _format_tokens(input_tokens: int, output_tokens: int) -> str:
    if not input_tokens and not output_tokens:
        return ""
    parts = []
    if input_tokens:
        parts.append(f"{CYAN}↑{_fmt_tok(input_tokens)}{RESET}")
    if output_tokens:
        parts.append(f"{MAGENTA}↓{_fmt_tok(output_tokens)}{RESET}")
    return " " + "/".join(parts)


def _shorten_model(model: str) -> str:
    m = model.lower()
    if "haiku" in m:
        return "haiku"
    if "sonnet" in m:
        return "sonnet"
    if "opus" in m:
        return "opus"
    return model


def _run_ccstatusline(session_json: str):
    """Run ccstatusline if available, return its output lines or empty list."""
    if not shutil.which("npx") and not shutil.which("ccstatusline"):
        return []
    cmd = "ccstatusline" if shutil.which("ccstatusline") else "npx -y ccstatusline@latest"
    try:
        r = subprocess.run(
            cmd, shell=True, input=session_json,
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.rstrip("\n").split("\n")
    except (subprocess.TimeoutExpired, OSError):
        pass
    return []


def main():
    # Read session data from stdin (Claude Code provides this)
    try:
        raw_input = sys.stdin.read()
        session = json.loads(raw_input) if raw_input.strip() else {}
    except (json.JSONDecodeError, ValueError):
        raw_input = ""
        session = {}

    # Try ccstatusline first — print its lines above dispatch status
    cc_lines = _run_ccstatusline(raw_input)
    for line in cc_lines:
        print(line)

    session_id = session.get("session_id", "")
    dispatches_dir = _find_dispatches_dir(session_id)
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
        model = _shorten_model(data.get("model", "?"))

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

        # Token counts
        in_tok = data.get("input_tokens", 0)
        out_tok = data.get("output_tokens", 0)
        tok_str = _format_tokens(in_tok, out_tok)

        entry = f"{BLUE}{model}{RESET}{DIM}({agent}){RESET} {DIM}{elapsed}s{RESET}{tok_str}"
        is_hanging = False
        if idle > 300:
            entry += f" {RED}⚠idle{RESET}"
            is_hanging = True
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

    # Build status lines
    if active:
        # Header line: count + cost summary
        header = f"{BOLD}{GREEN}{len(active)} running{RESET}"
        if total_cost > 0 or done_count > 0:
            header += f" {DIM}|{RESET} {YELLOW}${total_cost:.2f}{RESET} {DIM}({done_count} done){RESET}"
        if hanging > 0:
            header += f" {DIM}|{RESET} {BOLD}{RED}{hanging} hanging{RESET}"
        print(header)

        # Agent lines: 2 per line, max 6 agents (3 lines)
        shown = active[:6]
        for i in range(0, len(shown), 2):
            pair = shown[i:i+2]
            print("  " + f"  {DIM}|{RESET}  ".join(pair))
        if len(active) > 6:
            print(f"  {DIM}+{len(active) - 6} more{RESET}")
    else:
        line = f"{DIM}dispatch: idle{RESET}"
        if total_cost > 0 or done_count > 0:
            line += f" | {YELLOW}${total_cost:.2f}{RESET} ({done_count} done)"
        print(line)


if __name__ == "__main__":
    main()
