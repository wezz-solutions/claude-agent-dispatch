"""
Configuration resolution for AgentDispatch.
Resolution: runtime params -> project dispatch.json -> user dispatch.json -> defaults.json
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

PLUGIN_DIR = Path(os.environ.get(
    "DISPATCH_PLUGIN_DIR",
    str(Path(__file__).resolve().parent.parent),
))
DEFAULTS_PATH = PLUGIN_DIR / "config" / "defaults.json"


def _find_project_root() -> Path:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return cwd


def _discover_session_id(project_root: Path) -> str:
    """
    Discover Claude Code session_id from transcript files.
    Returns session UUID or empty string if not determinable.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9]", "-", str(project_root))
    state_dir = Path.home() / ".claude" / "projects" / sanitized
    if not state_dir.exists():
        return ""
    transcripts = sorted(
        state_dir.glob("*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if transcripts:
        return transcripts[0].stem
    return ""


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class DispatchConfig:
    def __init__(self):
        self._project_root = _find_project_root()
        self._config = self._resolve()
        self._session_id = _discover_session_id(self._project_root)

    def _resolve(self) -> dict:
        defaults = _load_json(DEFAULTS_PATH)

        user_path = Path.home() / ".claude" / "dispatch.json"
        user_cfg = _load_json(user_path)

        project_path = self._project_root / ".claude" / "dispatch.json"
        project_cfg = _load_json(project_path)

        merged = _deep_merge(defaults, user_cfg)
        merged = _deep_merge(merged, project_cfg)
        return merged

    @property
    def default_model(self) -> str:
        return self._config.get("default_model", "sonnet")

    @property
    def enforce_dispatch(self) -> bool:
        return self._config.get("enforce_dispatch", False)

    @property
    def max_concurrent(self) -> int:
        return self._config.get("max_concurrent", 4)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def dispatches_dir(self) -> Path:
        rel = self._config.get("dispatches_dir", ".claude/dispatches")
        base = self._project_root / rel
        if self._session_id:
            return base / self._session_id
        return base

    @property
    def audit_enabled(self) -> bool:
        return self._config.get("audit", True)

    @property
    def default_timeout(self) -> int:
        return self._config.get("default_timeout", 3600)

    @property
    def inactivity_threshold(self) -> int:
        return self._config.get("inactivity_threshold", 300)

    @property
    def providers(self) -> dict:
        return self._config.get("providers", {})

    @property
    def agents(self) -> dict:
        return self._config.get("agents", {})

    @property
    def project_root(self) -> Path:
        return self._project_root

    def resolve_model(self, model_alias: str = "") -> dict:
        """
        Resolve model alias to full dispatch config.

        Accepts: "sonnet", "opus", "ollama/qwen3:30b", "openai/gpt-4.1", or full model ID.
        Returns: {provider, backend, model_id, timeout, provider_config}
        """
        if not model_alias:
            model_alias = self.default_model

        provider_hint = ""
        if "/" in model_alias:
            parts = model_alias.split("/", 1)
            provider_hint = parts[0]
            model_alias = parts[1]

        for prov_name, prov_config in self.providers.items():
            if provider_hint and prov_name != provider_hint:
                continue
            models = prov_config.get("models", {})
            if model_alias in models:
                model_cfg = models[model_alias]
                return {
                    "provider": prov_name,
                    "backend": prov_config.get("backend", "claude-cli"),
                    "model_id": model_cfg.get("id", model_alias),
                    "timeout": model_cfg.get("timeout", self.default_timeout),
                    "provider_config": prov_config,
                    "tier": model_cfg.get("tier"),
                }

        prov_name = provider_hint or "anthropic"
        prov_cfg = self.providers.get(prov_name, {})
        return {
            "provider": prov_name,
            "backend": prov_cfg.get("backend", "claude-cli" if prov_name == "anthropic" else "opencode"),
            "model_id": model_alias,
            "timeout": self.default_timeout,
            "provider_config": prov_cfg,
        }

    def to_summary(self) -> str:
        lines = [
            f"Default model: {self.default_model}",
            f"Enforce dispatch: {self.enforce_dispatch}",
            f"Max concurrent: {self.max_concurrent}",
            f"Default timeout: {self.default_timeout}s",
            f"Inactivity threshold: {self.inactivity_threshold}s",
            f"Dispatches dir: {self.dispatches_dir}",
            f"Audit: {self.audit_enabled}",
            "",
            "Providers:",
        ]
        for name, prov in self.providers.items():
            backend = prov.get("backend", "claude-cli")
            models = list(prov.get("models", {}).keys())
            lines.append(f"  {name} ({backend}): {', '.join(models)}")
        lines.append("")
        lines.append("Agents:")
        for name, agent_cfg in self.agents.items():
            lines.append(f"  {name}: {agent_cfg.get('file', 'built-in')}")
        return "\n".join(lines)
