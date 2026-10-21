"""Per-session runtime state under .cplugin/sessions/<session_id>/.

A session directory records which Claude Code process owns it (pid plus the
process start time, so a recycled pid is not mistaken for the old session).
Dead sessions are reclaimed by process liveness, never by the age of their
files: a session can legitimately sit on one task for days.
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
AGENT_PROCESS_NAME = "claude"
# Session dirs without a recorded pid are only reclaimed once they look abandoned.
ORPHAN_MAX_AGE_SECONDS = 7 * 24 * 3600

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


def read_meta(directory: Path) -> dict | None:
    try:
        meta = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def register(project: Project, session_id: str, source: str, agent_pid: int | None) -> Path:
    """Create or refresh the session directory and its owner record."""
    directory = session_dir(project, session_id)
    directory.mkdir(parents=True, exist_ok=True)
    meta = read_meta(directory) or {"session_id": session_id, "started_at": time.time()}
    meta["pid"] = agent_pid
    meta["pid_start"] = process_start_time(agent_pid) if agent_pid else None
    meta["last_source"] = source
    meta["last_seen_at"] = time.time()
    write_atomic(directory / META_FILE, json.dumps(meta, indent=2) + "\n")
    return directory


def _owner_alive(meta: dict) -> bool | None:
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


def gc_dead_sessions(project: Project, keep: str | None) -> list[str]:
    """Remove session dirs whose owning process is gone. Returns removed names."""
    removed: list[str] = []
    if not project.sessions_dir.is_dir():
        return removed
    now = time.time()
    for entry in project.sessions_dir.iterdir():
        # Never follow symlinks: rmtree through a link would destroy its target.
        if entry.is_symlink() or not entry.is_dir() or entry.name == keep:
            continue
        meta = read_meta(entry)
        alive = _owner_alive(meta) if meta else None
        if alive is None:
            try:
                age = now - entry.stat().st_mtime
            except OSError:
                continue
            if age < ORPHAN_MAX_AGE_SECONDS:
                continue
        elif alive:
            continue
        try:
            shutil.rmtree(entry)
        except OSError:
            continue
        removed.append(entry.name)
    return removed
