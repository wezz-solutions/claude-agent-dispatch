"""
Sentinel file management for AgentDispatch.
Handles .marker/.done files for parallel-safe dispatch state tracking.
All writes are atomic (temp + rename) to prevent partial reads.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def generate_dispatch_id() -> str:
    return f"d-{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: dict):
    tmp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    if os.name == "nt" and path.exists():
        path.unlink()
    os.rename(str(tmp), str(path))


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError, AttributeError):
        return False


def _parse_iso(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


class SentinelManager:
    def __init__(self, dispatches_dir: Path):
        self.dir = dispatches_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    # ── Marker lifecycle ─────────────────────────────────────

    def write_marker(self, dispatch_id: str, pid: int, agent: str,
                     model: str, provider: str, backend: str,
                     prompt_preview: str, timeout: int):
        _atomic_write(self.dir / f"{dispatch_id}.marker", {
            "id": dispatch_id,
            "pid": pid,
            "agent": agent,
            "model": model,
            "provider": provider,
            "backend": backend,
            "prompt_preview": prompt_preview[:200],
            "started": _now_iso(),
            "timeout_seconds": timeout,
            "status": "RUNNING",
            "last_activity": _now_iso(),
        })

    def update_activity(self, dispatch_id: str, input_tokens: int = 0,
                        output_tokens: int = 0):
        path = self.dir / f"{dispatch_id}.marker"
        marker = _read_json(path)
        if marker:
            marker["last_activity"] = _now_iso()
            if input_tokens:
                marker["input_tokens"] = input_tokens
            if output_tokens:
                marker["output_tokens"] = output_tokens
            _atomic_write(path, marker)

    def update_marker_status(self, dispatch_id: str, status: str):
        path = self.dir / f"{dispatch_id}.marker"
        marker = _read_json(path)
        if marker:
            marker["status"] = status
            _atomic_write(path, marker)

    # ── Done lifecycle ───────────────────────────────────────

    def write_done(self, dispatch_id: str, result: dict):
        done_path = self.dir / f"{dispatch_id}.done"
        marker_path = self.dir / f"{dispatch_id}.marker"

        marker = _read_json(marker_path)
        if marker:
            result.setdefault("started", marker.get("started"))

        result["id"] = dispatch_id
        result["completed"] = _now_iso()

        started = _parse_iso(result.get("started", ""))
        completed = _parse_iso(result["completed"])
        if started and completed:
            result["duration_seconds"] = int((completed - started).total_seconds())

        _atomic_write(done_path, result)

        if marker_path.exists():
            try:
                marker_path.unlink()
            except OSError:
                pass

    def read_marker(self, dispatch_id: str) -> Optional[dict]:
        return _read_json(self.dir / f"{dispatch_id}.marker")

    def read_done(self, dispatch_id: str) -> Optional[dict]:
        return _read_json(self.dir / f"{dispatch_id}.done")

    # ── Status queries ───────────────────────────────────────

    def get_status(self, dispatch_id: str) -> dict:
        done = self.read_done(dispatch_id)
        if done:
            return {"status": done.get("status", "DONE"), "data": done}

        marker = self.read_marker(dispatch_id)
        if not marker:
            return {"status": "NOT_FOUND", "data": None}

        pid = marker.get("pid", 0)
        if pid and not _is_process_alive(pid):
            return {"status": "DEAD_PROCESS", "data": marker}

        # Compute idle time
        last_act = _parse_iso(marker.get("last_activity", ""))
        if last_act:
            idle = int((datetime.now(timezone.utc) - last_act).total_seconds())
            marker["idle_seconds"] = idle

        # Check timeout
        started = _parse_iso(marker.get("started", ""))
        timeout = marker.get("timeout_seconds", 3600)
        if started:
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            marker["elapsed_seconds"] = int(elapsed)
            if elapsed > timeout:
                return {"status": "TIMED_OUT", "data": marker}

        return {"status": marker.get("status", "RUNNING"), "data": marker}

    def list_active(self) -> list:
        self.cleanup_stale()
        active = []
        for mf in self.dir.glob("*.marker"):
            info = self.get_status(mf.stem)
            active.append(info)
        return active

    def list_completed(self, limit: int = 20) -> list:
        done_files = sorted(
            self.dir.glob("*.done"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        results = []
        for df in done_files[:limit]:
            data = _read_json(df)
            if data:
                results.append(data)
        return results

    # ── Cleanup ──────────────────────────────────────────────

    def cleanup_stale(self) -> list:
        cleaned = []
        for mf in self.dir.glob("*.marker"):
            marker = _read_json(mf)
            if not marker:
                continue
            pid = marker.get("pid", 0)
            if pid and not _is_process_alive(pid):
                self.write_done(mf.stem, {
                    "status": "DEAD_PROCESS",
                    "agent": marker.get("agent", ""),
                    "model": marker.get("model", ""),
                    "provider": marker.get("provider", ""),
                    "backend": marker.get("backend", ""),
                    "output": "Process died unexpectedly",
                    "exit_code": -1,
                })
                cleaned.append(mf.stem)
        return cleaned

    # ── Audit ────────────────────────────────────────────────

    def append_audit(self, dispatch_id: str, data: dict):
        audit_path = self.dir / "dispatch-audit.jsonl"
        entry = {"ts": _now_iso(), "id": dispatch_id, **data}
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
