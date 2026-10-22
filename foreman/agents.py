"""Which agents are working in a session, and on what.

One small file per agent under .foreman/sessions/<id>/agents/, so parallel
sub-agents never write the same file. MAIN's file is `main.json`. The hooks
keep these up to date; the board (milestone 4) renders them.
"""

from __future__ import annotations

import fcntl
import json
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .fsutil import write_atomic

AGENTS_DIR = "agents"
MAIN_KEY = "main"
# A sub-agent whose SubagentStop never arrived stops counting as running after this.
STALE_AFTER_SECONDS = 2 * 3600

_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def agent_key(payload: dict) -> str | None:
    agent_id = payload.get("agent_id")
    if not agent_id:
        return MAIN_KEY
    return agent_id if isinstance(agent_id, str) and _KEY_RE.match(agent_id) else None


def _path(session_dir: Path, key: str) -> Path:
    return session_dir / AGENTS_DIR / f"{key}.json"


def read(session_dir: Path, key: str) -> dict:
    try:
        data = json.loads(_path(session_dir, key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(session_dir: Path, key: str, record: dict) -> None:
    path = _path(session_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(record, indent=2) + "\n")


def record_start(session_dir: Path, key: str, agent_type: str, role: str) -> None:
    _write(session_dir, key, {"key": key, "agent_type": agent_type, "role": role,
                              "status": "running", "started_at": time.time()})


def record_action(session_dir: Path, key: str, role: str, tool: str, target: str) -> None:
    record = read(session_dir, key) or {"key": key, "role": role, "status": "running",
                                        "started_at": time.time()}
    record["last_action"] = {"tool": tool, "target": target[:200], "at": time.time()}
    _write(session_dir, key, record)


def record_stop(session_dir: Path, key: str) -> None:
    record = read(session_dir, key)
    if record:
        record.update(status="done", ended_at=time.time())
        _write(session_dir, key, record)


def all_records(session_dir: Path) -> list[dict]:
    directory = session_dir / AGENTS_DIR
    if not directory.is_dir():
        return []
    records = (read(session_dir, path.stem) for path in sorted(directory.glob("*.json")))
    return [r for r in records if r]


def last_activity(record: dict) -> float:
    return max(record.get("started_at", 0), (record.get("last_action") or {}).get("at", 0))


def is_running(record: dict, now: float) -> bool:
    return (record.get("key") != MAIN_KEY and record.get("status") == "running"
            and now - last_activity(record) < STALE_AFTER_SECONDS)


def running_subagents(session_dir: Path) -> list[dict]:
    now = time.time()
    return [r for r in all_records(session_dir) if is_running(r, now)]


# Starts approved by PreToolUse whose SubagentStart has not arrived yet: two Agent
# calls in one message both reach PreToolUse before either agent is recorded.
PENDING_DIR = "pending"
PENDING_TTL_SECONDS = 120


@contextmanager
def spawn_lock(session_dir: Path):
    """Serializes the count-then-approve of agent starts across parallel hooks."""
    path = session_dir / AGENTS_DIR / ".spawn.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _pending(session_dir: Path, role: str) -> list[Path]:
    """Live pending starts for `role`, oldest first; expired ones are removed."""
    directory = session_dir / AGENTS_DIR / PENDING_DIR
    now, live = time.time(), []
    for path in sorted(directory.glob(f"{role}-*.json")) if directory.is_dir() else []:
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age < PENDING_TTL_SECONDS:
            live.append(path)
        else:
            path.unlink(missing_ok=True)
    return live


def pending_count(session_dir: Path, role: str) -> int:
    return len(_pending(session_dir, role))


def add_pending(session_dir: Path, role: str) -> None:
    directory = session_dir / AGENTS_DIR / PENDING_DIR
    directory.mkdir(parents=True, exist_ok=True)
    write_atomic(directory / f"{role}-{time.time_ns()}-{uuid.uuid4().hex[:8]}.json", "{}\n")


def consume_pending(session_dir: Path, role: str) -> None:
    pending = _pending(session_dir, role)
    if pending:
        pending[0].unlink(missing_ok=True)


def action_target(payload: dict) -> str:
    tool_input = payload.get("tool_input") or {}
    for key in ("file_path", "notebook_path", "command", "pattern", "url", "description"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value.splitlines()[0]
    return ""
