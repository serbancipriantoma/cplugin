"""SubagentStart / SubagentStop: track sub-agents and brief the foreman roles.

SubagentStart records the agent (the board shows it, and the Stop hook lets
the main agent wait for it) and, while a task is active, tells the agent what
its role may and may not write. SubagentStop marks it finished.
"""

from __future__ import annotations

from pathlib import Path

from .. import agents, config, roles, session
from ..status import active_task
from .common import context, project_for, session_dir_for

ROLE_BRIEF = """[foreman] You are the {role} for task {title}, working on: {step}.
You may write: {own}.
You may not write: {forbidden}, task.md, MIND_MAP.md, mindmap/ or .foreman/. Hooks block those writes, and files you change through Bash are checked too.
Do not run `.claude/bin/tasks` commands; the main agent manages the task.
Finish with the report your instructions describe: it is all the main agent sees."""

OTHER_BRIEF = ("[foreman] Task {title} is active. While it is, only foreman:worker writes "
               "code and only foreman:tester writes tests; you may read and run commands.")


def handle_start(payload: dict, plugin_root: Path) -> dict | None:
    project = project_for(payload)
    directory = session_dir_for(project, payload) if project else None
    key = agents.agent_key(payload)
    if directory is None or key is None or key == agents.MAIN_KEY:
        return None
    role = roles.role_of(payload)
    agents.record_start(directory, key, str(payload.get("agent_type") or ""), role)
    agents.consume_pending(directory, role)

    state = session.read_state(directory)
    task = active_task(project, payload.get("session_id"))
    if task is None or state.get("freehand"):
        return None
    if role == roles.OTHER:
        return context("SubagentStart", OTHER_BRIEF.format(title=task.title))
    cfg = config.load_or_defaults(project)
    if role == roles.WORKER:
        other, own_kind, other_kind = roles.TESTER, "code files", "tests"
    else:
        other, own_kind, other_kind = roles.WORKER, "test files", "production code"
    own_paths = ", ".join(roles.role_paths(cfg, role)) or "none configured"
    other_paths = ", ".join(roles.role_paths(cfg, other)) or "none configured"
    gate = next((g for g in task.gates() if not g.checked), None)
    return context("SubagentStart", ROLE_BRIEF.format(
        role=role, title=task.title, step=gate.section if gate else "the current step",
        own=f"{own_kind} under {own_paths}", forbidden=f"{other_kind} ({other_paths})"))


def handle_stop(payload: dict, plugin_root: Path) -> dict | None:
    project = project_for(payload)
    directory = session_dir_for(project, payload) if project else None
    key = agents.agent_key(payload)
    if directory is not None and key is not None and key != agents.MAIN_KEY:
        agents.record_stop(directory, key)
    return None
