"""PostToolUse: keep the current gate in front of the main agent.

After every tool call it shows the active task's next gate. Once the agent has
spent a few calls on the same gate, it adds a question matched to what the
agent just did. It also keeps the per-turn counters the Stop hook reads.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import config, gates, session
from ..project import Project
from ..task import Task, find_task, task_for_path
from .common import WRITE_TOOLS, context, ensure_registered, project_for, session_dir_for, target_path

NUDGE_AFTER = 3      # calls on one gate before questions start
DRIFT_AFTER = 15     # calls on one gate before the drift warning
MAX_GATE_TEXT = 200

QUESTIONS = {
    "orient": (
        "What am I looking for?",
        "Do I already know enough to act?",
        "Does this serve the current gate?",
    ),
    "execute": (
        "Is this the simplest change that works?",
        "How will I verify this?",
        "Does this serve the request, or an idea of my own?",
    ),
    "test": (
        "Did I read the output, or skim it?",
        "Did it pass (or fail) for the right reason?",
        "Am I testing what the criteria say, or what is easy to test?",
    ),
    "reflect": (
        "Did I write the outcome on the gate I just checked?",
        "Does the next gate still make sense? If not, change it now.",
    ),
}

_ORIENT_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch"}
_TEST_RE = re.compile(
    r"\b(pytest|unittest|jest|vitest|mocha|playwright|go test|cargo test|(npm|pnpm|yarn|bun)( run)? test)\b"
)


def classify(project: Project, payload: dict, cfg: dict) -> str:
    tool = payload.get("tool_name", "")
    if tool in _ORIENT_TOOLS:
        return "orient"
    if tool in WRITE_TOOLS:
        target = target_path(project, payload)
        if target and target[1] and task_for_path(project, target[1]):
            return "reflect"
        return "execute"
    if tool == "Bash":
        command = str((payload.get("tool_input") or {}).get("command", ""))
        test_command = str(cfg.get("tests", {}).get("command") or "").strip()
        if (test_command and test_command in command) or _TEST_RE.search(command):
            return "test"
    return "operate"


def handle(payload: dict, plugin_root: Path) -> dict | None:
    project = project_for(payload)
    if project is None:
        return None
    if payload.get("agent_type"):
        return None  # sub-agents: milestone 3
    directory = session_dir_for(project, payload)
    if directory is None:
        return None
    ensure_registered(project, payload)

    counters = session.read_counters(directory)
    counters["turn_tools"] = counters.get("turn_tools", 0) + 1
    if payload.get("tool_name") in WRITE_TOOLS:
        counters["turn_writes"] = counters.get("turn_writes", 0) + 1

    state = session.read_state(directory)
    num = session.active_task(state)
    task = find_task(project, num) if num else None
    text = None
    if task is not None and not state.get("freehand"):
        text = _gate_echo(project, task, payload, counters)
    elif num:
        text = f"[cplugin] The active task {num:03d} no longer exists. Run `.claude/bin/tasks list`."
    session.write_counters(directory, counters)
    return context("PostToolUse", text) if text else None


def _gate_echo(project: Project, task: Task, payload: dict, counters: dict) -> str:
    all_gates = task.gates()
    gate = gates.first_open(all_gates)
    if gate is None:
        return f"[cplugin] Task {task.label}: every gate is checked. Run `.claude/bin/tasks done`."
    done, total = gates.progress(all_gates)
    key = f"{task.num}:{gate.line}:{gate.text}"
    calls = counters.get("gate_calls", 0) + 1 if counters.get("gate_key") == key else 1
    counters.update(gate_key=key, gate_calls=calls)

    rel = task.path.relative_to(project.root)
    lines = [f"[cplugin] Task {task.label} · gate {done + 1}/{total} · {rel}:{gate.line} "
             f"[{gate.section}] {gate.text[:MAX_GATE_TEXT]}"]
    kind = classify(project, payload, config.load_or_defaults(project))
    if calls >= NUDGE_AFTER and kind in QUESTIONS:
        questions = QUESTIONS[kind]
        lines.append(questions[calls % len(questions)])
    if calls >= DRIFT_AFTER and calls % 5 == 0:
        lines.append(f"{calls} tool calls on this gate. Is it done? If the plan no longer fits, "
                     "change the open gates now.")
    return "\n".join(lines)
