"""Stop: the main agent may not end its turn while the active task has open gates.

Exceptions: a conversational turn (no writes and fewer than 5 tool calls), a
`tasks pause` because the user is needed, sub-agents still running in the
background (the main agent ends its turn to wait for them), freehand, and
`stop_hook_active` (the agent is already continuing because of this hook;
blocking again would loop).
"""

from __future__ import annotations

from pathlib import Path

from .. import agents, gates, session
from ..task import find_task
from .common import project_for, session_dir_for

CONVERSATIONAL_MAX_TOOLS = 5

BLOCKED = """Task {label} has {open} unchecked gate(s). Next ({rel}:{line}) [{section}]: {text}

Keep working through the gates. If you need the user (a decision, an answer, a manual
check), run `.claude/bin/tasks pause "<what you need>"` and end the turn with the question.
If the remaining gates no longer fit the work, edit them."""


def handle(payload: dict, plugin_root: Path) -> dict | None:
    project = project_for(payload)
    if project is None:
        return None
    directory = session_dir_for(project, payload)
    if directory is None or not directory.is_dir():
        return None
    counters = session.read_counters(directory)
    state = session.read_state(directory)

    background = [t for t in payload.get("background_tasks") or [] if isinstance(t, dict)]
    waiting = any(t.get("status") == "running" for t in background) or bool(agents.running_subagents(directory))
    if not (payload.get("stop_hook_active") or waiting or state.get("freehand") or state.get("pause")):
        busy = counters.get("turn_writes", 0) > 0 or counters.get("turn_tools", 0) >= CONVERSATIONAL_MAX_TOOLS
        num = session.active_task(state)
        task = find_task(project, num) if num and busy else None
        if task is not None:
            all_gates = task.gates()
            gate = gates.first_open(all_gates)
            if gate is not None:
                return {"decision": "block", "reason": BLOCKED.format(
                    label=task.label, open=sum(not g.checked for g in all_gates),
                    rel=task.path.relative_to(project.root), line=gate.line,
                    section=gate.section, text=gate.text)}

    # The turn really ends: reset the per-turn counters and the one-turn pause.
    session.write_counters(directory, {**counters, "turn_tools": 0, "turn_writes": 0})
    if state.get("pause"):
        session.write_state(directory, {**state, "pause": None})
    return None
