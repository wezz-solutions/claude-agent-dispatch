"""
SessionStart hook: ensures dispatch.json and status line exist.
Runs automatically when Claude Code session starts (via plugin.json hooks).
Silent — only creates files if missing.
"""

import json
import sys
import os
from pathlib import Path

PLUGIN_DIR = Path(os.environ.get(
    "DISPATCH_PLUGIN_DIR",
    os.environ.get("CLAUDE_PLUGIN_ROOT", str(Path(__file__).resolve().parent.parent)),
))
DEFAULTS_PATH = PLUGIN_DIR / "config" / "defaults.json"


def _find_project_root() -> Path:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return cwd


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main():
    project_root = _find_project_root()

    # Create dispatch.json from defaults if missing
    for config_path in [
        project_root / ".claude" / "dispatch.json",
        Path.home() / ".claude" / "dispatch.json",
    ]:
        if config_path.exists():
            break
    else:
        config_path = project_root / ".claude" / "dispatch.json"
        defaults = _load_json(DEFAULTS_PATH)
        if defaults:
            _save_json(config_path, defaults)

    # Output nothing — silent hook
    print(json.dumps({"continue": True, "suppressOutput": True}))


if __name__ == "__main__":
    main()
