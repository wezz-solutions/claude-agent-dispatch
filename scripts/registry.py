"""
Agent definition registry.
Resolves agent names to definition text for prompt injection.
"""

import os
from pathlib import Path
from typing import Optional

PLUGIN_DIR = Path(os.environ.get(
    "DISPATCH_PLUGIN_DIR",
    str(Path(__file__).resolve().parent.parent),
))
AGENTS_DIR = PLUGIN_DIR / "agents"


class AgentRegistry:
    def __init__(self, config_agents: dict):
        self._config = config_agents

    def resolve(self, agent_name: str) -> tuple:
        """
        Resolve agent name to (definition_text, display_name).

        Resolution order:
        1. "" or "general" -> built-in general.md
        2. "raw" or "none" -> empty definition (prompt passes through)
        3. Key in config agents -> load that file
        4. File path (contains / or \\ or ends .md) -> load directly
        5. Name matching agents/{name}.md -> load built-in
        """
        if not agent_name or agent_name == "general":
            return self._load_builtin("general"), "general"

        if agent_name in ("raw", "none"):
            return "", "raw"

        if agent_name in self._config:
            file_path = self._config[agent_name].get("file", "")
            if file_path:
                full = PLUGIN_DIR / file_path if not Path(file_path).is_absolute() else Path(file_path)
                return self._load_file(full), agent_name

        if "/" in agent_name or "\\" in agent_name or agent_name.endswith(".md"):
            path = Path(agent_name)
            if not path.is_absolute():
                path = Path.cwd() / path
            return self._load_file(path), path.stem

        builtin = AGENTS_DIR / f"{agent_name}.md"
        if builtin.exists():
            return self._load_builtin(agent_name), agent_name

        available = ", ".join(self.list_available())
        raise ValueError(f"Unknown agent: '{agent_name}'. Available: {available}")

    def _load_builtin(self, name: str) -> str:
        return self._load_file(AGENTS_DIR / f"{name}.md")

    def _load_file(self, path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"Agent definition not found: {path}")
        return path.read_text(encoding="utf-8")

    def list_available(self) -> list:
        agents = set()
        if AGENTS_DIR.exists():
            for f in AGENTS_DIR.glob("*.md"):
                agents.add(f.stem)
        agents.update(self._config.keys())
        return sorted(agents)

    def get_default_tools(self, agent_name: str) -> Optional[str]:
        if agent_name in self._config:
            return self._config[agent_name].get("default_tools")
        return None

    def get_default_model(self, agent_name: str) -> Optional[str]:
        if agent_name in self._config:
            return self._config[agent_name].get("default_model")
        return None
