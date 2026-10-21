"""PostToolUse: keep the current gate in front of the main agent, and catch
files changed through Bash by a role that does not own them.

After every tool call of the main agent it shows the active task's next gate.
Once the agent has spent a few calls on the same gate, it adds a question
matched to what the agent just did. It also keeps the per-turn counters the
Stop hook reads. For every agent it records the last action (for the board),
and after a Bash call it compares the git status with the snapshot PreToolUse
took: a file changed by a role that does not own it is reported to the agent
and recorded in the task's Violations section.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .. import agents, bashcheck, config, gates, roles, session
from ..project import Project
from ..task import Task, find_task, record_violation, task_for_path
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
    directory = session_dir_for(project, payload)
    if directory is None:
        return None
    ensure_registered(project, payload)
    role = roles.role_of(payload)
    tool = payload.get("tool_name", "")
    key = agents.agent_key(payload)
    if key is not None:
        agents.record_action(directory, key, role, tool, agents.action_target(payload))

    state = session.read_state(directory)
    num = session.active_task(state)
    task = find_task(project, num) if num else None
    notes: list[str] = []

    if tool in WRITE_TOOLS:
        target = target_path(project, payload)
        if target and target[1]:
            bashcheck.log_tool_write(directory, target[1], target[0])
    elif tool == "Bash":
        before = bashcheck.pop(directory, str(payload.get("tool_use_id") or ""))
        if before is not None and task is not None and not state.get("freehand"):
            notes += _bash_violations(project, directory, task, role, before)

    if role == roles.MAIN:
        counters = session.read_counters(directory)
        counters["turn_tools"] = counters.get("turn_tools", 0) + 1
        if tool in WRITE_TOOLS:
            counters["turn_writes"] = counters.get("turn_writes", 0) + 1
        if task is not None and not state.get("freehand"):
            notes.insert(0, _gate_echo(project, task, payload, counters))
        elif num:
            notes.insert(0, f"[cplugin] The active task {num:03d} no longer exists. "
                            "Run `.claude/bin/tasks list`.")
        session.write_counters(directory, counters)
    return context("PostToolUse", "\n".join(notes)) if notes else None


def _bash_violations(project: Project, directory: Path, task: Task, role: str,
                     before: bashcheck.Snapshot) -> list[str]:
    cfg = config.load_or_defaults(project)
    notes = []
    for rel in bashcheck.bash_changes(directory, project.root, before):
        if rel.startswith(".cplugin/"):
            continue  # the CLI's own state and task files
        reason = roles.write_violation(role, rel, project.root / rel, cfg)
        if reason is None:
            continue
        owner = roles.owner(rel, project.root / rel, cfg)
        stamp = time.strftime("%Y-%m-%d %H:%M")
        record_violation(task, f"{stamp} {role} changed `{rel}` through Bash (owner: {owner})")
        who = "main agent" if role == roles.MAIN else role
        notes.append(f"[cplugin] Role violation: as the {who} you changed {rel} through Bash, "
                     f"and it belongs to the {owner}. Undo your change to that file and leave it "
                     f"to its owner. This was recorded in {task.path.name}.")
    return notes


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
