"""Per-session runtime state under .foreman/sessions/<session_id>/.

- meta.json: which Claude Code process owns the session (pid plus the process
  start time, so a recycled pid is not mistaken for the old session).
- state.json: the active task and the session's mode, written by the CLI.
- counters.json: per-turn and per-gate counters, written by the hooks.

`claude --continue` resumes the same session_id in a new process, so state must
outlive the process. A session is reclaimed only when its owner is gone AND it
has been idle for a week; a live session is never reclaimed, however old.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .fsutil import write_atomic
from .project import Project

META_FILE = "meta.json"
STATE_FILE = "state.json"
COUNTERS_FILE = "counters.json"
ENV_VAR = "FOREMAN_SESSION_ID"
AGENT_PROCESS_NAME = "claude"
IDLE_MAX_AGE_SECONDS = 7 * 24 * 3600

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def safe_session_id(raw: object) -> str | None:
    """Return `raw` if it is usable as a directory name, else None."""
    if isinstance(raw, str) and _SESSION_ID_RE.match(raw):
        return raw
    return None


def _ps(pid: int, *fields: str) -> str | None:
    # One `-o field=` per field: `-o a,b=` blanks only the last header.
    columns = [arg for f in fields for arg in ("-o", f"{f}=")]
    try:
        out = subprocess.run(
            ["ps", *columns, "-p", str(pid)],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = out.stdout.strip()
    return text if out.returncode == 0 and text else None


def process_start_time(pid: int) -> str | None:
    return _ps(pid, "lstart")


def find_agent_pid(start_pid: int | None = None, max_depth: int = 8) -> int | None:
    """Walk up the process tree to the Claude Code process that runs this hook."""
    if start_pid is None:
        override = os.environ.get("FOREMAN_AGENT_PID")
        if override is not None:  # lets tests pin the owning process
            return int(override) if override.isdigit() else None
    pid = start_pid if start_pid is not None else os.getppid()
    for _ in range(max_depth):
        if pid <= 1:
            return None
        line = _ps(pid, "ppid", "comm")
        if line is None:
            return None
        ppid_text, _, comm = line.partition(" ")
        if os.path.basename(comm.strip()) == AGENT_PROCESS_NAME:
            return pid
        try:
            pid = int(ppid_text)
        except ValueError:
            return None
    return None


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    except (OverflowError, ValueError, OSError):
        return False
    return True


def session_dir(project: Project, session_id: str) -> Path:
    return project.sessions_dir / session_id


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
    write_atomic(path, json.dumps(data, indent=2) + "\n")


def read_meta(directory: Path) -> dict | None:
    return _read_json(directory / META_FILE)


def read_state(directory: Path) -> dict:
    return _read_json(directory / STATE_FILE) or {}


def write_state(directory: Path, state: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _write_json(directory / STATE_FILE, state)


def read_counters(directory: Path) -> dict:
    return _read_json(directory / COUNTERS_FILE) or {}


def write_counters(directory: Path, counters: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _write_json(directory / COUNTERS_FILE, counters)


def active_task(state: dict) -> int | None:
    task = state.get("task")
    return task if isinstance(task, int) and task > 0 else None


def register(project: Project, session_id: str, source: str, agent_pid: int | None) -> Path:
    """Create or refresh the session directory and its owner record."""
    directory = session_dir(project, session_id)
    directory.mkdir(parents=True, exist_ok=True)
    meta = read_meta(directory) or {"session_id": session_id, "started_at": time.time()}
    meta["pid"] = agent_pid
    meta["pid_start"] = process_start_time(agent_pid) if agent_pid else None
    meta["last_source"] = source
    meta["last_seen_at"] = time.time()
    meta.pop("ended_at", None)
    meta.pop("end_reason", None)
    _write_json(directory / META_FILE, meta)
    return directory


def mark_ended(project: Project, session_id: str, reason: str) -> None:
    directory = session_dir(project, session_id)
    meta = read_meta(directory)
    if meta is None:
        return
    meta["ended_at"] = time.time()
    meta["end_reason"] = reason
    _write_json(directory / META_FILE, meta)


def owner_alive(meta: dict) -> bool | None:
    """True/False when the owner is known, None when the session recorded no pid."""
    pid = meta.get("pid")
    if not isinstance(pid, int):
        return None
    if not pid_alive(pid):
        return False
    recorded_start = meta.get("pid_start")
    if recorded_start:
        current_start = process_start_time(pid)
        if current_start and current_start != recorded_start:
            return False  # pid recycled by an unrelated process
    return True


def _last_activity(directory: Path) -> float:
    times = [directory.stat().st_mtime]
    for child in directory.iterdir():
        try:
            times.append(child.stat().st_mtime)
        except OSError:
            continue
    return max(times)


def session_dirs(project: Project) -> list[Path]:
    if not project.sessions_dir.is_dir():
        return []
    # Never follow symlinks: rmtree through a link would destroy its target.
    return [d for d in project.sessions_dir.iterdir() if d.is_dir() and not d.is_symlink()]


def gc_dead_sessions(project: Project, keep: str | None) -> list[str]:
    """Remove sessions whose owner is gone and that have been idle for a week."""
    removed: list[str] = []
    now = time.time()
    for entry in session_dirs(project):
        if entry.name == keep:
            continue
        meta = read_meta(entry)
        if meta and owner_alive(meta):
            continue
        try:
            idle = now - _last_activity(entry)
        except OSError:
            continue
        if idle < IDLE_MAX_AGE_SECONDS:
            continue
        try:
            shutil.rmtree(entry)
        except OSError:
            continue
        removed.append(entry.name)
    return removed


def _same_process(meta: dict | None, agent_pid: int) -> bool:
    if not meta or meta.get("pid") != agent_pid:
        return False
    return owner_alive(meta) is True


def inherit_from_same_process(project: Project, session_id: str, agent_pid: int | None) -> int | None:
    """After /clear the same process may start a new session_id. Move the active
    task of its previous session over, so the work survives the clear."""
    if agent_pid is None:
        return None
    own = session_dir(project, session_id)
    if active_task(read_state(own)):
        return None
    candidates = []
    for entry in session_dirs(project):
        if entry.name == session_id:
            continue
        meta = read_meta(entry)
        state = read_state(entry)
        if _same_process(meta, agent_pid) and active_task(state):
            candidates.append((meta.get("last_seen_at") or 0, entry, state))
    if not candidates:
        return None
    _, previous, state = max(candidates, key=lambda c: c[0])
    write_state(own, state)
    write_state(previous, {**state, "task": None, "handed_to": session_id})
    return active_task(state)


def resolve_cli_session(project: Project) -> str | None:
    """Which session a `tasks` command belongs to: FOREMAN_SESSION_ID when the
    environment carries it, else the session registered by the Claude Code
    process this command runs under."""
    env_id = safe_session_id(os.environ.get(ENV_VAR))
    if env_id and session_dir(project, env_id).is_dir():
        return env_id
    agent_pid = find_agent_pid()
    if agent_pid is None:
        return None
    best: tuple[float, str] | None = None
    for entry in session_dirs(project):
        meta = read_meta(entry)
        if _same_process(meta, agent_pid):
            seen = meta.get("last_seen_at") or 0
            if best is None or seen > best[0]:
                best = (seen, entry.name)
    return best[1] if best else None


def live_sessions_with_task(project: Project, task: int, exclude: str | None = None) -> list[str]:
    found = []
    for entry in session_dirs(project):
        if entry.name == exclude:
            continue
        meta = read_meta(entry)
        if meta and owner_alive(meta) and active_task(read_state(entry)) == task:
            found.append(entry.name)
    return found
