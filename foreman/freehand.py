"""Freehand: the user drives, and foreman's rules are suspended.

While it is on, the hooks no longer require a task for code, enforce roles or
hold the main agent's turn. Only the user turns it on (/foreman:freehand runs
the CLI directly; the hook refuses `tasks freehand` from any agent). It ends
with `tasks work <N>` or `tasks freehand off`, and what changed meanwhile, the
commits and the files, is appended to .foreman/freehand.md so it is not lost.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import bashcheck, gitutil, session
from .fsutil import write_atomic
from .project import Project

LOG_FILE = "freehand.md"
LOG_HEADER = "# Freehand log\n\nWhat changed while the user drove without a task (written by foreman).\n"


def is_on(state: dict) -> bool:
    return bool(state.get("freehand"))


def start(project: Project, session_dir: Path, paused_task: int | None) -> dict:
    record = {"since": time.time(), "head": gitutil.head(project.root),
              "snapshot": bashcheck.take(project.root) or {}, "paused_task": paused_task}
    state = session.read_state(session_dir)
    session.write_state(session_dir, {**state, "task": None, "pause": None, "freehand": record})
    return record


def _changes(project: Project, record: dict) -> tuple[list[str], list[str]]:
    """Commits made since freehand started, and the files changed (committed or not)."""
    head = record.get("head")
    commits: list[str] = []
    files = set(bashcheck.changed(record.get("snapshot") or {}, bashcheck.take(project.root) or {}))
    current = gitutil.head(project.root)
    if head and current and head != current:
        log = gitutil.git(project.root, "log", "--format=%h %s", f"{head}..{current}") or b""
        commits = log.decode("utf-8", "replace").splitlines()
        names = gitutil.git(project.root, "diff", "--name-only", head, current, "--", ".") or b""
        files |= set(names.decode("utf-8", "replace").splitlines())
    return commits, sorted(f for f in files if f and not f.startswith(".foreman/"))


def stop(project: Project, session_dir: Path, session_id: str) -> str:
    """End freehand, log what changed, and return a summary for the agent."""
    state = session.read_state(session_dir)
    record = state.get("freehand")
    if not record:
        return "Freehand was not on."
    session.write_state(session_dir, {**state, "freehand": None})
    commits, files = _changes(project, record)
    since = time.strftime("%Y-%m-%d %H:%M", time.localtime(record.get("since", time.time())))
    entry = [f"\n## {since} → {time.strftime('%H:%M')} (session {session_id[:8]})"]
    entry.append(f"- commits: {len(commits)}" + "".join(f"\n  - {c}" for c in commits))
    entry.append(f"- files changed: {', '.join(f'`{f}`' for f in files) or 'none'}")
    log = project.state_dir / LOG_FILE
    existing = log.read_text(encoding="utf-8") if log.is_file() else LOG_HEADER
    write_atomic(log, existing.rstrip("\n") + "\n" + "\n".join(entry) + "\n")

    lines = [f"Freehand off. Since {since}: {len(commits)} commit(s), {len(files)} file(s) changed"
             + (f": {', '.join(files[:10])}" + (" …" if len(files) > 10 else "") if files else ".")]
    lines.append(f"Logged in .foreman/{LOG_FILE}.")
    if files:
        lines.append("If this changed behaviour, update the owning section in mindmap/ "
                     "(and MIND_MAP.md if the big ideas changed).")
    if record.get("paused_task"):
        lines.append(f"Task {record['paused_task']:03d} was paused when freehand began: "
                     f"`.claude/bin/tasks work {record['paused_task']}` resumes it.")
    return "\n".join(lines)
