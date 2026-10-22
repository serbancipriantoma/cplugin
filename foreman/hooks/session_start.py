"""SessionStart: register the session, refresh launchers, load the project memory.

Fires on startup, resume, clear and compact, so the map and the active task
are back in context after every compaction. Outside a foreman project it does
nothing.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import config, containment, environment, mindmap, session, status, wrappers
from ..project import Project, find_legacy_root, find_project_root


def _export_session_id(session_id: str) -> None:
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        with open(env_file, "a", encoding="utf-8") as fh:
            fh.write(f"export {session.ENV_VAR}={session_id}\n")


def handle(payload: dict, plugin_root: Path) -> dict | None:
    cwd = payload.get("cwd") or os.getcwd()
    root = find_project_root(cwd)
    if root is None:
        legacy = find_legacy_root(cwd)
        if legacy is None:
            return None
        note = (f"foreman: {legacy} still uses the layout from before the plugin was renamed "
                "(.cplugin/). Run /foreman:init to move it to .foreman/; until then foreman is inactive here.")
        return {"systemMessage": note,
                "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": note}}
    project = Project(root)
    warnings: list[str] = []

    session_id = session.safe_session_id(payload.get("session_id"))
    if session_id is None:
        warnings.append("no usable session_id in the SessionStart payload; session state not recorded")
    else:
        # Each step is independent: one failing must not cost the others.
        try:
            _export_session_id(session_id)
        except OSError as exc:
            warnings.append(f"could not write CLAUDE_ENV_FILE: {exc}")
        agent_pid = session.find_agent_pid()
        try:
            session.register(project, session_id, str(payload.get("source") or "startup"), agent_pid)
            inherited = session.inherit_from_same_process(project, session_id, agent_pid)
            if inherited:
                warnings.append(f"took over active task {inherited:03d} from the previous session of this process")
        except OSError as exc:
            warnings.append(f"could not record session state: {exc}")
        try:
            session.gc_dead_sessions(project, keep=session_id)
        except OSError as exc:
            warnings.append(f"could not clean up old sessions: {exc}")

    try:
        wrappers.ensure_launchers(project, plugin_root)
    except OSError as exc:
        warnings.append(f"could not write .claude/bin launchers: {exc}")

    task = status.active_task(project, session_id)
    state = session.read_state(session.session_dir(project, session_id)) if session_id else {}
    since = (state.get("freehand") or {}).get("since")
    cfg = config.load_or_defaults(project, warnings)
    banner = environment.banner(project, cfg, task, containment.detect(), since)
    # The banner goes to the user (systemMessage) and, for the main agent, into the context.
    summary = f"{status.task_summary(project, task, since)}\n\nThis session, as shown to the user:\n{banner}"
    return {
        "systemMessage": banner,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": mindmap.session_context(project, warnings, summary),
        },
    }
