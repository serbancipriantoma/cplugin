"""PreToolUse: stop work from bypassing the task system.

- Code edits need an active task.
- Only `tasks new` creates a task.md; session state belongs to the CLI.
- The active task's gates are checked one at a time: 3+ in one write is
  blocked, 2 is warned about, and a check with no outcome written is pointed out.

Unreadable session state reads as "no active task", so the no-task rule fails closed.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import codefiles, config, gates, session
from ..project import Project
from ..task import parse_dir_name, task_for_path
from .common import WRITE_TOOLS, context, ensure_registered, pre_tool_deny, project_for, \
    session_dir_for, target_path

NO_TASK = """No active task. Code edits need one, so the work is planned and tracked.

  1. .claude/bin/tasks new <type> <name> --module <module> --request - <<'EOF'
     <the user's request, verbatim>
     EOF
  2. .claude/bin/tasks work <N>
  3. Work the gates in task.md, one at a time.

To resume an existing task: .claude/bin/tasks work <N> (`.claude/bin/tasks list` shows them)."""

MANUAL_TASK = ("Only `.claude/bin/tasks new <type> <name>` creates task files: it numbers them "
               "and fills in the template.")
SESSION_STATE = ("Session state under .cplugin/sessions/ is managed by the hooks and the "
                 "`.claude/bin/tasks` CLI. Use the CLI.")
TOO_MANY = ("You checked {n} gates in one edit. Work gate by gate: do one gate's work, then "
            "check it and write its outcome on the same line.")

_MKDIR_TASK_RE = re.compile(r"\bmkdir\b[^;&|\n]*\.cplugin/tasks/")
# A redirect, tee or in-place edit whose target is a task.md or session state.
_STATE_PATH = r"""['"]?[^\s;&|'"]*\.cplugin/(?:tasks/[^/\s'"]+/task\.md|sessions/)"""
_SHELL_WRITE_RE = re.compile(
    rf"(?:>>?|\btee\b(?:\s+-a)?)\s*{_STATE_PATH}"
    rf"|\b(?:sed|perl)\s+(?:-[a-zA-Z]*i\b|--in-place)[^;&|\n]*\.cplugin/(?:tasks/[^/\s]+/task\.md|sessions/)"
)


def handle(payload: dict, plugin_root: Path) -> dict | None:
    project = project_for(payload)
    if project is None:
        return None
    ensure_registered(project, payload)
    tool = payload.get("tool_name", "")
    if tool in WRITE_TOOLS:
        return _check_write(project, payload)
    if tool == "Bash":
        return _check_bash(payload)
    return None


def _state(project: Project, payload: dict) -> dict:
    directory = session_dir_for(project, payload)
    return session.read_state(directory) if directory else {}


def _check_write(project: Project, payload: dict) -> dict | None:
    target = target_path(project, payload)
    if target is None or target[1] is None:
        return None  # no path, or outside the project
    abs_path, rel = target
    if rel.startswith(".cplugin/sessions/"):
        return pre_tool_deny(SESSION_STATE)
    state = _state(project, payload)
    task_dir = task_for_path(project, rel)
    if task_dir is not None:
        if payload.get("tool_name") == "Write" and not abs_path.exists():
            return pre_tool_deny(MANUAL_TASK)
        return _check_gates(payload, task_dir, abs_path, state)
    if rel.startswith((".cplugin/", ".claude/")):
        return None
    if session.active_task(state) or state.get("freehand"):
        return None
    if codefiles.is_code_file(rel, abs_path, config.load_or_defaults(project)):
        return pre_tool_deny(NO_TASK)
    return None


def _check_gates(payload: dict, task_dir: str, abs_path: Path, state: dict) -> dict | None:
    parsed = parse_dir_name(task_dir)
    if parsed is None or parsed[0] != session.active_task(state):
        return None  # only the active task's gates are policed
    tool = payload.get("tool_name")
    ti = payload.get("tool_input") or {}
    current = abs_path.read_text(encoding="utf-8") if abs_path.is_file() else ""
    if tool == "Edit":
        edits = [ti]
    elif tool == "MultiEdit":
        edits = [e for e in ti.get("edits") or [] if isinstance(e, dict)]
    elif tool == "Write":
        new = str(ti.get("content", ""))
        delta = gates.progress(gates.parse(new))[0] - gates.progress(gates.parse(current))[0]
        return _verdict(delta, gates.bare_checks(current, new))
    else:
        return None
    delta, bare = 0, []
    for edit in edits:
        old, new = str(edit.get("old_string", "")), str(edit.get("new_string", ""))
        step = gates.checked_count(new) - gates.checked_count(old)
        if edit.get("replace_all") and step > 0 and old:
            step *= max(current.count(old), 1)
        delta += step
        bare += gates.bare_checks(old, new)
    return _verdict(delta, bare)


def _verdict(delta: int, bare: list[str]) -> dict | None:
    if delta >= 3:
        return pre_tool_deny(TOO_MANY.format(n=delta))
    notes = []
    if delta == 2:
        notes.append("You checked 2 gates in one edit. Work gate by gate: each gate gets its own work and outcome.")
    if bare:
        quoted = "; ".join(f'"{text[:80]}"' for text in bare[:3])
        notes.append(f"Checked without an outcome: {quoted}. Append what happened on the same line.")
    return context("PreToolUse", "[cplugin] " + " ".join(notes)) if notes else None


def _check_bash(payload: dict) -> dict | None:
    command = str((payload.get("tool_input") or {}).get("command", ""))
    if _MKDIR_TASK_RE.search(command):
        return pre_tool_deny(MANUAL_TASK)
    if _SHELL_WRITE_RE.search(command):
        return pre_tool_deny("Task files are edited with the Edit tool, one gate at a time, and "
                             "session state belongs to the `.claude/bin/tasks` CLI.")
    return None
