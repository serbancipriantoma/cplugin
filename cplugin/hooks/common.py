"""Helpers shared by the hook handlers."""

from __future__ import annotations

import os
from pathlib import Path

from .. import session
from ..project import Project, find_project_root

# Tools that write files, and the input key holding the target path.
WRITE_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path",
               "NotebookEdit": "notebook_path"}


def project_for(payload: dict) -> Project | None:
    root = find_project_root(payload.get("cwd") or os.getcwd())
    return Project(root) if root else None


def session_dir_for(project: Project, payload: dict) -> Path | None:
    session_id = session.safe_session_id(payload.get("session_id"))
    return session.session_dir(project, session_id) if session_id else None


def ensure_registered(project: Project, payload: dict) -> None:
    """A session that started before /cplugin:init never ran SessionStart in this
    project. Register it on first contact so the `tasks` CLI can find it."""
    session_id = session.safe_session_id(payload.get("session_id"))
    if session_id and not (session.session_dir(project, session_id) / session.META_FILE).is_file():
        session.register(project, session_id, "late", session.find_agent_pid())


def target_path(project: Project, payload: dict) -> tuple[Path, str | None] | None:
    """Absolute target of a write tool, and its POSIX path relative to the
    project root (None when it lies outside the project)."""
    key = WRITE_TOOLS.get(payload.get("tool_name", ""))
    raw = (payload.get("tool_input") or {}).get(key) if key else None
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path(payload.get("cwd") or os.getcwd()) / path
    path = Path(os.path.normpath(path))
    try:
        rel = path.resolve().relative_to(project.root.resolve()).as_posix()
    except (ValueError, OSError):
        rel = None
    return path, rel


def pre_tool_deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def context(event: str, text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}
