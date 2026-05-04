"""
Agent definition registry.
Resolves agent names to definition text for prompt injection.
Auto-discovers agents from plugin, project, and user directories.
"""

import os
from pathlib import Path
from typing import Optional

PLUGIN_DIR = Path(os.environ.get(
    "DISPATCH_PLUGIN_DIR",
    os.environ.get("CLAUDE_PLUGIN_ROOT", str(Path(__file__).resolve().parent.parent)),
))
AGENTS_DIR = PLUGIN_DIR / "agents"


def _find_project_root() -> Path:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return cwd


def _discovery_dirs() -> list[Path]:
    """Agent search directories in priority order (first match wins)."""
    project = _find_project_root()
    return [
        project / ".claude" / "agents",
        project / "agents",
        Path.home() / ".claude" / "agents",
        AGENTS_DIR,
    ]


def _discover_agent(name: str) -> Optional[Path]:
    """Search standard directories for {name}.md. Returns first match."""
    for d in _discovery_dirs():
        candidate = d / f"{name}.md"
        if candidate.exists():
            return candidate
    return None


class AgentRegistry:
    def __init__(self, config_agents: dict):
        self._config = config_agents

    def resolve(self, agent_name: str) -> tuple:
        """
        Resolve agent name to (definition_text, display_name).

        Resolution order:
        1. "" or "general" -> built-in general.md
        2. "raw" or "none" -> empty definition (prompt passes through)
        3. Key in dispatch.json agents -> load configured file
        4. File path (contains / or \\ or ends .md) -> load directly
        5. Auto-discover from: project .claude/agents/, project agents/,
           user ~/.claude/agents/, plugin agents/
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

        discovered = _discover_agent(agent_name)
        if discovered:
            return self._load_file(discovered), agent_name

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
        for d in _discovery_dirs():
            if d.exists():
                for f in d.glob("*.md"):
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
