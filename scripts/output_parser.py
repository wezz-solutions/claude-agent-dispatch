"""
Parse backend output into standardized DispatchResult.
Handles Claude CLI JSON output and OpenCode JSON output.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class DispatchResult:
    status: str = "DONE"
    output: str = ""
    files_modified: list = field(default_factory=list)
    summary: str = ""
    model: str = ""
    provider: str = ""
    backend: str = ""
    exit_code: int = 0
    cost_usd: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items()
                if v is not None and v != [] and v != ""}


def parse_claude_cli_output(stdout: str, stderr: str, exit_code: int,
                            model: str, provider: str) -> DispatchResult:
    result = DispatchResult(
        model=model, provider=provider, backend="claude-cli", exit_code=exit_code,
    )

    if exit_code != 0:
        result.status = "FAILED"
        result.output = stderr.strip() or stdout.strip() or f"Exit code {exit_code}"
        return result

    try:
        data = json.loads(stdout)
        result.output = data.get("result", stdout)
        result.cost_usd = data.get("total_cost_usd")
        usage = data.get("usage", {})
        result.input_tokens = (
            (usage.get("input_tokens") or 0)
            + (usage.get("cache_read_input_tokens") or 0)
            + (usage.get("cache_creation_input_tokens") or 0)
        )
        result.output_tokens = usage.get("output_tokens")
    except (json.JSONDecodeError, KeyError):
        result.output = stdout.strip()

    result.status = _extract_status(result.output)
    result.files_modified = _extract_files(result.output)
    result.summary = _extract_summary(result.output)
    return result


def parse_opencode_output(stdout: str, stderr: str, exit_code: int,
                          model: str, provider: str) -> DispatchResult:
    result = DispatchResult(
        model=model, provider=provider, backend="opencode", exit_code=exit_code,
    )

    if exit_code != 0:
        result.status = "FAILED"
        result.output = stderr.strip() or stdout.strip() or f"Exit code {exit_code}"
        return result

    try:
        data = json.loads(stdout)
        result.output = data.get("response", stdout)
    except (json.JSONDecodeError, KeyError):
        result.output = stdout.strip()

    result.status = _extract_status(result.output)
    result.files_modified = _extract_files(result.output)
    result.summary = _extract_summary(result.output)
    return result


def _extract_status(output: str) -> str:
    upper = output.upper()
    for s in ("BLOCKED", "FAILED", "NEEDS_CONTEXT"):
        if f"STATUS**: {s}" in upper or f"STATUS: {s}" in upper:
            return s
    return "DONE"


def _extract_files(output: str) -> list:
    files = []
    for pattern in [
        r"\*\*FILES(?:_MODIFIED)?\*\*:\s*(.*?)(?:\n\n|\Z)",
        r"Files (?:modified|changed):\s*(.*?)(?:\n\n|\Z)",
    ]:
        match = re.search(pattern, output, re.IGNORECASE | re.DOTALL)
        if match:
            for line in match.group(1).strip().split("\n"):
                cleaned = line.strip().lstrip("- *`").rstrip("`")
                if cleaned and ("/" in cleaned or "\\" in cleaned or "." in cleaned):
                    files.append(cleaned)
            break
    return files


def _extract_summary(output: str) -> str:
    for pattern in [
        r"\*\*SUMMARY\*\*:\s*(.*?)(?:\n|$)",
        r"SUMMARY:\s*(.*?)(?:\n|$)",
    ]:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    for line in output.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("**"):
            return line[:200]
    return ""


def format_result_for_claude(dispatch_id: str, result: DispatchResult,
                             duration_seconds: int = 0) -> str:
    lines = [f"## Dispatch {dispatch_id} — {result.status}", ""]

    meta = f"**Model:** {result.model} ({result.provider}/{result.backend})"
    if duration_seconds:
        meta += f" | **Duration:** {duration_seconds}s"
    if result.cost_usd is not None:
        meta += f" | **Cost:** ${result.cost_usd:.4f}"
    lines.append(meta)

    if result.summary:
        lines.append(f"**Summary:** {result.summary}")

    if result.files_modified:
        lines += ["", "### Files Modified"]
        for f in result.files_modified:
            lines.append(f"- {f}")

    lines += ["", "### Output", result.output]
    return "\n".join(lines)
