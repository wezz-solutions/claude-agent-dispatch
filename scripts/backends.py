"""
Dispatch backends: Claude CLI, OpenCode CLI, and Interactive terminal.
Each backend spawns a subprocess and monitors output for hang detection.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional

from output_parser import (
    DispatchResult, parse_claude_cli_output, parse_opencode_output,
    _extract_status, _extract_files, _extract_summary,
)


def _dbg(msg: str):
    print(f"[dispatch {time.time():.1f}] {msg}", file=sys.stderr, flush=True)


class DispatchBackend(ABC):
    @abstractmethod
    async def run(
        self,
        prompt: str,
        agent_definition: str,
        model_id: str,
        provider: str,
        working_dir: Path,
        timeout: int,
        dispatch_id: str = "",
        on_activity: Optional[Callable] = None,
        inactivity_threshold: int = 300,
        provider_config: Optional[dict] = None,
        tier: Optional[str] = None,
    ) -> DispatchResult:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def backend_name(self) -> str:
        ...


TIER_TO_CLI_MODEL = {
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
    "opus": "claude-opus-4-6",
}

_alias_hashes: dict[str, str] = {}
_alias_lock = asyncio.Lock()


async def _get_ollama_hashes() -> dict[str, str]:
    """Parse `ollama list` output into {model_name: hash} dict."""
    proc = await asyncio.create_subprocess_exec(
        "ollama", "list",
        stdin=subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    result = {}
    for line in stdout.decode("utf-8", errors="replace").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0].removesuffix(":latest")
            result[name] = parts[1]
    return result


class ClaudeCLIBackend(DispatchBackend):
    """Dispatch via Claude CLI headless mode (claude --bare -p)."""

    def backend_name(self) -> str:
        return "claude-cli"

    def is_available(self) -> bool:
        return shutil.which("claude") is not None

    async def _ensure_ollama_alias(self, real_model: str, cli_model: str):
        """Ensure cli_model alias in Ollama points to real_model. Hash-checked, lock-serialized."""
        cached_hash = _alias_hashes.get(cli_model)
        if cached_hash:
            source_hash = _alias_hashes.get(real_model)
            if source_hash and cached_hash == source_hash:
                return

        async with _alias_lock:
            hashes = await _get_ollama_hashes()
            _alias_hashes.update(hashes)

            source_hash = hashes.get(real_model, "")
            alias_hash = hashes.get(cli_model, "")

            if source_hash and source_hash == alias_hash:
                _dbg(f"alias ok: {cli_model} -> {real_model} ({source_hash[:8]})")
                return

            _dbg(f"alias set: {cli_model} -> {real_model} (was {alias_hash[:8] if alias_hash else 'missing'})")
            proc = await asyncio.create_subprocess_exec(
                "ollama", "cp", real_model, cli_model,
                stdin=subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)
            _alias_hashes[cli_model] = source_hash

    async def run(self, prompt, agent_definition, model_id, provider,
                  working_dir, timeout, dispatch_id="", on_activity=None,
                  inactivity_threshold=300, provider_config=None,
                  tier=None) -> DispatchResult:
        cli_model_id = model_id
        if tier and tier in TIER_TO_CLI_MODEL and provider_config and provider_config.get("base_url"):
            cli_model_id = TIER_TO_CLI_MODEL[tier]
            await self._ensure_ollama_alias(model_id, cli_model_id)

        cmd = [
            "claude",
            "-p",
            "--model", cli_model_id,
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--no-session-persistence",
            "--dangerously-skip-permissions",
        ]

        full_prompt = (
            f"{agent_definition}\n\n---\n\nTask:\n{prompt}"
            if agent_definition else prompt
        )

        env = {**os.environ}
        depth = int(env.get("DISPATCH_DEPTH", "0"))
        env["DISPATCH_DEPTH"] = str(depth + 1)
        if dispatch_id:
            env["DISPATCH_ID"] = dispatch_id

        # Ollama/custom provider: redirect Claude CLI to local API
        if provider_config and provider_config.get("base_url"):
            env["ANTHROPIC_BASE_URL"] = provider_config["base_url"]
            env["ANTHROPIC_AUTH_TOKEN"] = "ollama"
            env["ANTHROPIC_API_KEY"] = ""

        _dbg(f"run: model={cli_model_id} provider={provider} dispatch={dispatch_id}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(working_dir),
            env=env,
        )

        try:
            proc.stdin.write(full_prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass

        stderr_buf = []
        last_activity = time.time()
        hanging_flagged = False
        result_event = None
        token_state = {"input": 0, "output": 0, "output_chars": 0}

        async def _read_stdout():
            nonlocal last_activity, hanging_flagged, result_event
            buffer = b""
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    if buffer.strip():
                        self._parse_stream_line(
                            buffer.decode("utf-8", errors="replace"),
                            token_state, on_activity,
                        )
                        if result_event is None:
                            try:
                                evt = json.loads(buffer)
                                if evt.get("type") == "result":
                                    result_event = evt
                            except (json.JSONDecodeError, ValueError):
                                pass
                    break
                buffer += chunk
                last_activity = time.time()
                hanging_flagged = False
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue
                    evt = self._parse_stream_line(line_str, token_state, on_activity)
                    if evt and evt.get("type") == "result":
                        result_event = evt

        async def _read_stderr():
            nonlocal last_activity
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break
                stderr_buf.append(chunk)
                last_activity = time.time()

        async def _monitor_hang():
            nonlocal hanging_flagged
            while proc.returncode is None:
                await asyncio.sleep(30)
                idle = time.time() - last_activity
                if idle > inactivity_threshold and not hanging_flagged:
                    hanging_flagged = True
                    if on_activity:
                        on_activity()

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _read_stdout(),
                    _read_stderr(),
                    _monitor_hang(),
                    proc.wait(),
                ),
                timeout=timeout,
            )
            _dbg(f"done: model={cli_model_id} rc={proc.returncode}")
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            return DispatchResult(
                status="TIMEOUT",
                output=f"Timed out after {timeout}s",
                model=model_id, provider=provider, backend="claude-cli",
                exit_code=-1,
                input_tokens=token_state["input"] or None,
                output_tokens=token_state["output"] or None,
            )

        stderr = b"".join(stderr_buf).decode("utf-8", errors="replace")

        if result_event:
            return self._result_from_event(result_event, model_id, provider, token_state)

        # Fallback: no result event parsed
        return DispatchResult(
            status="FAILED" if proc.returncode else "DONE",
            output=stderr.strip() or "No result event received",
            model=model_id, provider=provider, backend="claude-cli",
            exit_code=proc.returncode or 0,
            input_tokens=token_state["input"] or None,
            output_tokens=token_state["output"] or None,
        )

    def _parse_stream_line(self, line: str, token_state: dict,
                           on_activity: Optional[Callable]) -> Optional[dict]:
        try:
            evt = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None

        updated = False

        # Count output chars from text_delta events (real-time estimate)
        if evt.get("type") == "stream_event":
            delta = evt.get("event", {}).get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                token_state["output_chars"] += len(text)
                # Estimate: ~4 chars per token
                token_state["output"] = token_state["output_chars"] // 4
                updated = True

        # assistant events: per-turn context window size
        elif evt.get("type") == "assistant":
            usage = evt.get("message", {}).get("usage", {})
            if usage:
                # Show current turn's context window (not cumulative)
                token_state["input"] = (
                    (usage.get("input_tokens") or 0)
                    + (usage.get("cache_read_input_tokens") or 0)
                    + (usage.get("cache_creation_input_tokens") or 0)
                )
                updated = True

        # result event: final accurate output count, keep last turn's input
        elif evt.get("type") == "result":
            usage = evt.get("usage", {})
            if usage:
                # Use actual output_tokens from result (accurate final count)
                token_state["output"] = usage.get("output_tokens") or 0
                # For input, use per-iteration data if available (last turn context)
                iters = usage.get("iterations", [])
                if iters:
                    last_iter = iters[-1]
                    token_state["input"] = (
                        (last_iter.get("input_tokens") or 0)
                        + (last_iter.get("cache_read_input_tokens") or 0)
                        + (last_iter.get("cache_creation_input_tokens") or 0)
                    )
                updated = True

        if updated and on_activity:
            on_activity(
                input_tokens=token_state["input"],
                output_tokens=token_state["output"],
            )
        elif on_activity:
            on_activity()

        return evt

    def _result_from_event(self, evt: dict, model_id: str, provider: str,
                           token_state: dict) -> DispatchResult:
        usage = evt.get("usage", {})
        # Use last iteration for input (per-turn context, not cumulative sum)
        iters = usage.get("iterations", [])
        if iters:
            last_iter = iters[-1]
            input_tokens = (
                (last_iter.get("input_tokens") or 0)
                + (last_iter.get("cache_read_input_tokens") or 0)
                + (last_iter.get("cache_creation_input_tokens") or 0)
            )
        else:
            input_tokens = (
                (usage.get("input_tokens") or 0)
                + (usage.get("cache_read_input_tokens") or 0)
                + (usage.get("cache_creation_input_tokens") or 0)
            )
        output_tokens = usage.get("output_tokens") or 0

        result = DispatchResult(
            status="DONE" if not evt.get("is_error") else "FAILED",
            output=evt.get("result", ""),
            model=model_id,
            provider=provider,
            backend="claude-cli",
            exit_code=0 if not evt.get("is_error") else 1,
            cost_usd=evt.get("total_cost_usd"),
            input_tokens=input_tokens or token_state.get("input") or None,
            output_tokens=output_tokens or token_state.get("output") or None,
        )
        result.status = _extract_status(result.output)
        result.files_modified = _extract_files(result.output)
        result.summary = _extract_summary(result.output)
        return result


class OpenCodeBackend(DispatchBackend):
    """Dispatch via OpenCode CLI (opencode -p) for non-Anthropic models."""

    def backend_name(self) -> str:
        return "opencode"

    def is_available(self) -> bool:
        return shutil.which("opencode") is not None

    async def run(self, prompt, agent_definition, model_id, provider,
                  working_dir, timeout, dispatch_id="", on_activity=None,
                  inactivity_threshold=300, provider_config=None,
                  tier=None) -> DispatchResult:
        full_prompt = (
            f"{agent_definition}\n\n---\n\nTask:\n{prompt}"
            if agent_definition else prompt
        )

        cmd = [
            "opencode",
            "-p", full_prompt,
            "-f", "json",
            "-q",
        ]

        env = {**os.environ}
        depth = int(env.get("DISPATCH_DEPTH", "0"))
        env["DISPATCH_DEPTH"] = str(depth + 1)
        if dispatch_id:
            env["DISPATCH_ID"] = dispatch_id

        # Model routing via Viper env binding
        opencode_provider = provider
        provider_cfg = {}  # caller may pass this via provider_config
        if model_id:
            env["OPENCODE_AGENTS_CODER_MODEL"] = (
                f"{opencode_provider}/{model_id}" if opencode_provider else model_id
            )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(working_dir),
            env=env,
        )

        stdout_buf = []
        stderr_buf = []
        last_activity = time.time()

        async def _read_stdout():
            nonlocal last_activity
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                stdout_buf.append(chunk)
                last_activity = time.time()
                if on_activity:
                    on_activity()

        async def _read_stderr():
            nonlocal last_activity
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break
                stderr_buf.append(chunk)
                last_activity = time.time()

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _read_stdout(),
                    _read_stderr(),
                    proc.wait(),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            return DispatchResult(
                status="TIMEOUT",
                output=f"Timed out after {timeout}s",
                model=model_id, provider=provider, backend="opencode",
                exit_code=-1,
            )

        stdout = b"".join(stdout_buf).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_buf).decode("utf-8", errors="replace")
        return parse_opencode_output(stdout, stderr, proc.returncode or 0, model_id, provider)


class InteractiveBackend:
    """Launch interactive terminal session for human-in-the-loop dispatch."""

    @staticmethod
    def is_windows_terminal() -> bool:
        return "WT_SESSION" in os.environ

    @staticmethod
    def is_tmux() -> bool:
        return "TMUX" in os.environ

    @staticmethod
    async def launch(
        prompt: str,
        agent_definition: str,
        model_id: str,
        working_dir: Path,
        dispatch_id: str,
        dispatches_dir: Path,
    ) -> int:
        """
        Launch interactive terminal session.
        Returns PID of launched process.
        """
        dispatches_dir.mkdir(parents=True, exist_ok=True)

        # Write prompt file for reference
        prompt_file = dispatches_dir / f"{dispatch_id}.prompt"
        full_prompt = (
            f"{agent_definition}\n\n---\n\nTask:\n{prompt}"
            if agent_definition else prompt
        )
        prompt_file.write_text(full_prompt, encoding="utf-8")

        # Build claude command
        claude_cmd = ["claude", "--model", model_id]
        if agent_definition:
            agent_file = dispatches_dir / f"{dispatch_id}.agent.md"
            agent_file.write_text(agent_definition, encoding="utf-8")
            claude_cmd += ["--append-system-prompt-file", str(agent_file)]

        launch_env = {
            **os.environ,
            "DISPATCH_DEPTH": "1",
            "DISPATCH_ID": dispatch_id,
        }

        if sys.platform == "win32":
            if InteractiveBackend.is_windows_terminal():
                title = f"Dispatch {dispatch_id}"
                full_cmd = [
                    "wt", "-w", "0", "sp",
                    "--title", title,
                    "-d", str(working_dir),
                    "--",
                ] + claude_cmd
            else:
                full_cmd = ["cmd", "/c", "start",
                            f"Dispatch {dispatch_id}",
                            "cmd", "/k"] + claude_cmd

            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                cwd=str(working_dir),
                env=launch_env,
            )
        else:
            if InteractiveBackend.is_tmux():
                cmd_str = " ".join(claude_cmd)
                full_cmd = [
                    "tmux", "split-window", "-h",
                    "-c", str(working_dir),
                    cmd_str,
                ]
            else:
                full_cmd = claude_cmd

            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                cwd=str(working_dir),
                env=launch_env,
            )

        return proc.pid
