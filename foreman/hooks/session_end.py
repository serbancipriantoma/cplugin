"""SessionEnd: note that the session closed, and keep its state.

`claude --continue` resumes the same session_id, so the active task must
survive the exit. Old sessions are reclaimed by SessionStart's sweep.
"""

from __future__ import annotations

from pathlib import Path

from .. import session
from .common import project_for


def handle(payload: dict, plugin_root: Path) -> dict | None:
    project = project_for(payload)
    session_id = session.safe_session_id(payload.get("session_id"))
    if project is not None and session_id:
        session.mark_ended(project, session_id, str(payload.get("reason") or "other"))
    return None
