"""
Dispatch backends: Claude CLI, OpenCode CLI, and Interactive terminal.
Each backend spawns a subprocess and monitors output for hang detection.
"""

import asyncio
import json
import os
import shutil
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional

from output_parser import DispatchResult, parse_claude_cli_output, parse_opencode_output


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
    ) -> DispatchResult:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def backend_name(self) -> str:
        ...


class ClaudeCLIBackend(DispatchBackend):
    """Dispatch via Claude CLI headless mode (claude --bare -p)."""

    def backend_name(self) -> str:
        return "claude-cli"

    def is_available(self) -> bool:
        return shutil.which("claude") is not None

    async def run(self, prompt, agent_definition, model_id, provider,
                  working_dir, timeout, dispatch_id="", on_activity=None,
                  inactivity_threshold=300) -> DispatchResult:
        cmd = [
            "claude",
            "-p",
            "--model", model_id,
            "--output-format", "json",
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

        stdout_buf = []
        stderr_buf = []
        last_activity = time.time()
        hanging_flagged = False

        async def _read_stdout():
            nonlocal last_activity, hanging_flagged
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                stdout_buf.append(chunk)
                last_activity = time.time()
                hanging_flagged = False
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

        async def _monitor_hang():
            nonlocal hanging_flagged
            while proc.returncode is None:
                await asyncio.sleep(30)
                idle = time.time() - last_activity
                if idle > inactivity_threshold and not hanging_flagged:
                    hanging_flagged = True
                    if on_activity:
                        on_activity()  # triggers marker update even for "hanging" signal

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
            )

        stdout = b"".join(stdout_buf).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_buf).decode("utf-8", errors="replace")
        return parse_claude_cli_output(stdout, stderr, proc.returncode or 0, model_id, provider)


class OpenCodeBackend(DispatchBackend):
    """Dispatch via OpenCode CLI (opencode -p) for non-Anthropic models."""

    def backend_name(self) -> str:
        return "opencode"

    def is_available(self) -> bool:
        return shutil.which("opencode") is not None

    async def run(self, prompt, agent_definition, model_id, provider,
                  working_dir, timeout, dispatch_id="", on_activity=None,
                  inactivity_threshold=300) -> DispatchResult:
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
