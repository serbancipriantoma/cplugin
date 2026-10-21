"""Where a session stands: its active task and next gate. Shared by the CLI and the hooks."""

from __future__ import annotations

from . import gates, session
from .project import Project
from .task import Task, find_task


def active_task(project: Project, session_id: str | None) -> Task | None:
    if not session_id:
        return None
    num = session.active_task(session.read_state(session.session_dir(project, session_id)))
    return find_task(project, num) if num else None


def where(project: Project, task: Task) -> str:
    all_gates = task.gates()
    done, total = gates.progress(all_gates)
    gate = gates.first_open(all_gates)
    if gate is None:
        return f"Progress {done}/{total}: every gate is checked. Run `.claude/bin/tasks done`."
    rel = task.path.relative_to(project.root)
    return f"Progress {done}/{total}. Next gate ({rel}:{gate.line}) [{gate.section}]: {gate.text}"


def task_summary(project: Project, task: Task | None) -> str:
    if task is None:
        return ("No active task. Code edits need one: `.claude/bin/tasks new <type> <name> "
                "--module <module> --request -` (the user's request on stdin), then "
                "`.claude/bin/tasks work <N>`.")
    return f"Active task: {task.title}. {where(project, task)}"
