"""
AgentDispatch MCP Server.
Exposes 6 tools: run, interactive, status, result, cancel, config.
Transport: stdio (auto-started by .mcp.json).
"""

import asyncio
import os
import signal
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from mcp.server.fastmcp import FastMCP

from config import DispatchConfig
from sentinel import SentinelManager, generate_dispatch_id
from registry import AgentRegistry
from backends import ClaudeCLIBackend, OpenCodeBackend, InteractiveBackend
from output_parser import DispatchResult, format_result_for_claude

mcp = FastMCP("dispatch")

_config: DispatchConfig = None
_sentinel: SentinelManager = None
_registry: AgentRegistry = None
_backends: dict = {}


def _init():
    global _config, _sentinel, _registry, _backends
    _config = DispatchConfig()
    _sentinel = SentinelManager(_config.dispatches_dir)
    _registry = AgentRegistry(_config.agents)
    _backends = {
        "claude-cli": ClaudeCLIBackend(),
        "opencode": OpenCodeBackend(),
    }


def _ensure_init():
    if _config is None:
        _init()


def _get_backend(name: str):
    backend = _backends.get(name)
    if not backend:
        raise ValueError(f"Unknown backend: {name}. Available: {list(_backends.keys())}")
    if not backend.is_available():
        if name == "opencode":
            raise RuntimeError(
                "OpenCode CLI not installed. Non-Anthropic models require OpenCode.\n"
                "Install: go install github.com/opencode-ai/opencode@latest\n"
                "Or download from https://github.com/opencode-ai/opencode/releases"
            )
        raise RuntimeError(
            f"Backend '{name}' CLI not found in PATH.\n"
            "For claude-cli: npm install -g @anthropic-ai/claude-code"
        )
    return backend


# ═══════════════════════════════════════════════════════════
#  Tool: run  (headless dispatch)
# ═══════════════════════════════════════════════════════════

@mcp.tool("run")
async def run(query: str, prompt: str, agent: str = "", model: str = "") -> str:
    """
    Dispatch a headless agent to perform a task. Blocks until completion.

    Args:
        query: Short label (max 20 chars) — what will be done, e.g. "Fix auth bug"
        prompt: Full task description for the agent
        agent: Agent type or path to .md file. Empty = general purpose.
               Built-in: general, explore, reviewer, implementer.
               Special: "raw" = no agent definition (prompt goes directly).
               Custom: file path to your own agent .md
        model: Model alias or provider/model. Empty = config default.
               Anthropic: "sonnet", "opus", "haiku"
               Ollama: "ollama/qwen3:30b", "ollama/qwen3:235b"
               OpenAI: "openai/gpt-4.1"
               Or any alias defined in dispatch.json
    """
    _ensure_init()

    resolved = _config.resolve_model(model)
    backend = _get_backend(resolved["backend"])
    agent_def, agent_name = _registry.resolve(agent)
    dispatch_id = generate_dispatch_id()
    timeout = resolved["timeout"]

    last_activity_ts = [time.time()]

    def on_activity():
        last_activity_ts[0] = time.time()
        try:
            _sentinel.update_activity(dispatch_id)
        except Exception:
            pass

    _sentinel.write_marker(
        dispatch_id=dispatch_id,
        pid=os.getpid(),
        agent=agent_name,
        model=resolved["model_id"],
        provider=resolved["provider"],
        backend=resolved["backend"],
        prompt_preview=query[:20],
        timeout=timeout,
    )

    try:
        result = await backend.run(
            prompt=prompt,
            agent_definition=agent_def,
            model_id=resolved["model_id"],
            provider=resolved["provider"],
            working_dir=_config.project_root,
            timeout=timeout,
            dispatch_id=dispatch_id,
            on_activity=on_activity,
            inactivity_threshold=_config.inactivity_threshold,
        )

        done_data = result.to_dict()
        done_data["agent"] = agent_name
        _sentinel.write_done(dispatch_id, done_data)

        if _config.audit_enabled:
            _sentinel.append_audit(dispatch_id, {
                "agent": agent_name,
                "model": resolved["model_id"],
                "provider": resolved["provider"],
                "backend": resolved["backend"],
                "status": result.status,
                "cost_usd": result.cost_usd,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            })

        done = _sentinel.read_done(dispatch_id)
        duration = done.get("duration_seconds", 0) if done else 0
        return format_result_for_claude(dispatch_id, result, duration)

    except Exception as e:
        _sentinel.write_done(dispatch_id, {
            "status": "FAILED",
            "agent": agent_name,
            "model": resolved["model_id"],
            "provider": resolved["provider"],
            "backend": resolved["backend"],
            "output": str(e),
            "exit_code": -1,
        })
        return f"## Dispatch {dispatch_id} — FAILED\n\n**Error:** {e}"


# ═══════════════════════════════════════════════════════════
#  Tool: interactive  (terminal session)
# ═══════════════════════════════════════════════════════════

@mcp.tool("interactive")
async def interactive(query: str, prompt: str, agent: str = "", model: str = "") -> str:
    """
    Open an interactive agent session in a new terminal window/pane.
    User can communicate with the agent directly. Non-blocking — returns immediately.

    On Windows Terminal: splits current pane.
    On tmux: splits current window.
    Otherwise: opens new terminal window.

    Args:
        query: Short label (max 20 chars)
        prompt: Initial task/context for the agent
        agent: Agent type or path (empty = general)
        model: Model alias (empty = config default, Anthropic only for interactive)
    """
    _ensure_init()

    resolved = _config.resolve_model(model)
    agent_def, agent_name = _registry.resolve(agent)
    dispatch_id = generate_dispatch_id()

    try:
        pid = await InteractiveBackend.launch(
            prompt=prompt,
            agent_definition=agent_def,
            model_id=resolved["model_id"],
            working_dir=_config.project_root,
            dispatch_id=dispatch_id,
            dispatches_dir=_config.dispatches_dir,
        )

        _sentinel.write_marker(
            dispatch_id=dispatch_id,
            pid=pid,
            agent=agent_name,
            model=resolved["model_id"],
            provider=resolved["provider"],
            backend="interactive",
            prompt_preview=query[:20],
            timeout=28800,
        )

        return (
            f"## Interactive Dispatch {dispatch_id}\n\n"
            f"**Model:** {resolved['model_id']} | **Agent:** {agent_name}\n\n"
            f"Terminal session opened. Interact with the agent directly.\n"
            f"Initial prompt written to: {_config.dispatches_dir / f'{dispatch_id}.prompt'}\n\n"
            f"Check status: `mcp__dispatch__status(id=\"{dispatch_id}\")`\n"
            f"Get result after session ends: `mcp__dispatch__result(id=\"{dispatch_id}\")`"
        )

    except Exception as e:
        return f"## Interactive Dispatch — FAILED\n\n**Error:** {e}"


# ═══════════════════════════════════════════════════════════
#  Tool: status
# ═══════════════════════════════════════════════════════════

@mcp.tool("status")
async def status(query: str, id: str = "") -> str:
    """
    Check dispatch status. Empty id = list all active dispatches.

    Args:
        query: Short label (max 20 chars) — e.g. "Check agent status"
        id: Dispatch ID (e.g. "d-a1b2c3d4"). Empty = list all active.
    """
    _ensure_init()
    _sentinel.cleanup_stale()

    if id:
        info = _sentinel.get_status(id)
        st = info["status"]
        data = info["data"]

        if st == "NOT_FOUND":
            return f"Dispatch {id}: NOT FOUND"

        lines = [f"## Dispatch {id} — {st}"]
        if data:
            lines.append(
                f"**Agent:** {data.get('agent', '?')} | "
                f"**Model:** {data.get('model', '?')} | "
                f"**Backend:** {data.get('backend', '?')}"
            )
            if data.get("started"):
                lines.append(f"**Started:** {data['started']}")
            elapsed = data.get("elapsed_seconds")
            if elapsed is not None:
                lines.append(f"**Elapsed:** {elapsed}s")

            idle = data.get("idle_seconds")
            if idle is not None and st in ("RUNNING", "POSSIBLY_HANGING"):
                if idle > _config.inactivity_threshold:
                    lines.append(
                        f"**WARNING: No activity for {idle}s — possibly hanging.** "
                        f"Consider cancelling with mcp__dispatch__cancel."
                    )
                else:
                    lines.append(f"**Last activity:** {idle}s ago")

            if st == "DEAD_PROCESS":
                lines.append("**Process died unexpectedly.** Check logs or re-dispatch.")

        return "\n".join(lines)

    # List all active
    active = _sentinel.list_active()
    if not active:
        # Also show recent completed
        recent = _sentinel.list_completed(limit=5)
        if recent:
            lines = ["No active dispatches.", "", "Recent completed:"]
            for d in recent:
                lines.append(
                    f"- **{d.get('id','?')}** {d.get('status','?')} — "
                    f"{d.get('agent','?')}/{d.get('model','?')} "
                    f"({d.get('duration_seconds',0)}s)"
                )
            return "\n".join(lines)
        return "No active or recent dispatches."

    lines = ["## Active Dispatches", ""]
    for item in active:
        data = item.get("data", {})
        st = item["status"]
        did = data.get("id", "?")
        agent = data.get("agent", "?")
        model = data.get("model", "?")
        idle = data.get("idle_seconds", 0)
        elapsed = data.get("elapsed_seconds", 0)

        line = f"- **{did}** ({st}) — {agent}/{model} [{elapsed}s elapsed]"
        if idle and idle > _config.inactivity_threshold:
            line += f" | idle {idle}s"
        lines.append(line)

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  Tool: result
# ═══════════════════════════════════════════════════════════

@mcp.tool("result")
async def result(query: str, id: str) -> str:
    """
    Get completed dispatch result. If still running, polls up to 60s.

    Args:
        query: Short label (max 20 chars) — e.g. "Get auth fix result"
        id: Dispatch ID (required)
    """
    _ensure_init()

    done = _sentinel.read_done(id)
    if done:
        r = DispatchResult(
            status=done.get("status", "DONE"),
            output=done.get("output", ""),
            files_modified=done.get("files_modified", []),
            summary=done.get("summary", ""),
            model=done.get("model", ""),
            provider=done.get("provider", ""),
            backend=done.get("backend", ""),
            cost_usd=done.get("cost_usd"),
        )
        return format_result_for_claude(id, r, done.get("duration_seconds", 0))

    marker = _sentinel.read_marker(id)
    if not marker:
        return f"Dispatch {id}: NOT FOUND"

    for _ in range(12):
        await asyncio.sleep(5)
        done = _sentinel.read_done(id)
        if done:
            r = DispatchResult(
                status=done.get("status", "DONE"),
                output=done.get("output", ""),
                files_modified=done.get("files_modified", []),
                summary=done.get("summary", ""),
                model=done.get("model", ""),
                provider=done.get("provider", ""),
                backend=done.get("backend", ""),
                cost_usd=done.get("cost_usd"),
            )
            return format_result_for_claude(id, r, done.get("duration_seconds", 0))

    elapsed = marker.get("elapsed_seconds", "?")
    return (
        f"Dispatch {id} still running after 60s poll (total {elapsed}s).\n"
        f"Use `mcp__dispatch__status(id=\"{id}\")` to check later."
    )


# ═══════════════════════════════════════════════════════════
#  Tool: cancel
# ═══════════════════════════════════════════════════════════

@mcp.tool("cancel")
async def cancel(query: str, id: str) -> str:
    """
    Cancel a running dispatch by terminating its process.

    Args:
        query: Short label (max 20 chars) — e.g. "Cancel stuck agent"
        id: Dispatch ID to cancel
    """
    _ensure_init()

    marker = _sentinel.read_marker(id)
    if not marker:
        done = _sentinel.read_done(id)
        if done:
            return f"Dispatch {id} already completed: {done.get('status', '?')}"
        return f"Dispatch {id}: NOT FOUND"

    pid = marker.get("pid", 0)
    if pid:
        try:
            if sys.platform == "win32":
                os.system(f"taskkill /F /PID {pid} /T 2>nul")
            else:
                os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

    _sentinel.write_done(id, {
        "status": "CANCELLED",
        "agent": marker.get("agent", ""),
        "model": marker.get("model", ""),
        "provider": marker.get("provider", ""),
        "backend": marker.get("backend", ""),
        "output": "Cancelled by user",
        "exit_code": -1,
    })

    if _config.audit_enabled:
        _sentinel.append_audit(id, {
            "agent": marker.get("agent", ""),
            "model": marker.get("model", ""),
            "provider": marker.get("provider", ""),
            "status": "CANCELLED",
        })

    return f"Dispatch {id} cancelled."


# ═══════════════════════════════════════════════════════════
#  Tool: config
# ═══════════════════════════════════════════════════════════

@mcp.tool("config")
async def config(query: str) -> str:
    """
    Show current dispatch configuration: models, agents, providers, backends.

    Args:
        query: Short label (max 20 chars) — e.g. "Show dispatch config"
    """
    _ensure_init()

    lines = [_config.to_summary(), ""]

    lines.append("Backend availability:")
    for name, backend in _backends.items():
        avail = "available" if backend.is_available() else "NOT INSTALLED"
        lines.append(f"  {name}: {avail}")

    lines.append("")
    lines.append("Available agents:")
    for a in _registry.list_available():
        tools = _registry.get_default_tools(a)
        suffix = f" (tools: {tools})" if tools else ""
        lines.append(f"  {a}{suffix}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    _init()
    mcp.run(transport="stdio")
