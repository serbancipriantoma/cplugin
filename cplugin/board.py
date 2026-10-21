"""The ASCII board: which agent is working, and on what.

    ┌ TASK 007 · project-filter ─ gate 9/18 ───────────────────────┐
    │ 3. Work Plan › Step 2: category filter — Red: the tests fai… │
    ├─────────┬────────────┬───────────────────────────────────────┤
    │ MAIN    │ ● waiting  │ for worker, tester                    │
    │ worker  │ ● Edit     │ src/projects/filter.ts           0:42 │
    │ tester  │ ● Bash     │ node --test tests/projects       0:38 │
    │ judge   │ ○ —        │                                       │
    └─────────┴────────────┴───────────────────────────────────────┘

It reads what the hooks record under .cplugin/sessions/<id>/ and draws it;
it never writes anything.
"""

from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import agents, gates, roles, session, status
from .project import Project

ACTIVE, IDLE = "●", "○"
MAIN_BUSY_SECONDS = 60          # MAIN counts as working this long after its last tool call
RECENT_DONE_SECONDS = 30 * 60   # a finished sub-agent stays on the board this long
NAME_WIDTH, STATUS_WIDTH = 9, 12
MIN_WIDTH, MAX_WIDTH = 50, 100


@dataclass(frozen=True)
class Row:
    name: str
    active: bool
    status: str
    detail: str = ""
    elapsed: str = ""


@dataclass(frozen=True)
class Board:
    title: str
    subtitle: str
    rows: list[Row]


def duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def age(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def _relative(target: str, project: Project) -> str:
    """Drop the project root from paths, also inside shell commands."""
    return target.replace(str(project.root) + "/", "")


def _action(record: dict, project: Project) -> tuple[str, str]:
    action = record.get("last_action") or {}
    return str(action.get("tool") or ""), _relative(str(action.get("target") or ""), project)


def _main_row(record: dict, running: list[dict], project: Project, now: float) -> Row:
    tool, target = _action(record, project)
    last = (record.get("last_action") or {}).get("at", 0)
    newest_start = max((r.get("started_at", 0) for r in running), default=0)
    if running and last <= newest_start + 1:
        waiting_for = ", ".join(sorted({r.get("role") if r.get("role") != roles.OTHER
                                        else r.get("agent_type", "agent") for r in running}))
        return Row("MAIN", True, "waiting", f"for {waiting_for}")
    if last and now - last < MAIN_BUSY_SECONDS:
        return Row("MAIN", True, tool or "working", target, age(now - last))
    return Row("MAIN", False, "idle", target, age(now - last) if last else "")


def _agent_row(record: dict, project: Project, now: float, name: str) -> Row:
    tool, target = _action(record, project)
    if agents.is_running(record, now):
        return Row(name, True, tool or "starting", target, duration(now - record.get("started_at", now)))
    ended = record.get("ended_at") or agents.last_activity(record)
    return Row(name, False, "done", target, age(now - ended))


def collect(project: Project, session_id: str | None, now: float | None = None) -> Board:
    now = time.time() if now is None else now
    directory = session.session_dir(project, session_id) if session_id else None
    state = session.read_state(directory) if directory else {}
    task = status.active_task(project, session_id)

    if task is None:
        title, subtitle = "NO ACTIVE TASK", "start one: tasks new <type> <name>, then tasks work <N>"
    else:
        all_gates = task.gates()
        gate = gates.first_open(all_gates)
        done, total = gates.progress(all_gates)
        title = f"TASK {task.label} · {task.slug} ─ gate {min(done + 1, total)}/{total}"
        subtitle = f"{gate.section} — {gate.text}" if gate else "every gate is checked: tasks done"
    if state.get("freehand"):
        title += " · FREEHAND"
    if state.get("pause"):
        subtitle = f"waiting for the user: {state['pause']}"

    records = agents.all_records(directory) if directory else []
    main = next((r for r in records if r.get("key") == agents.MAIN_KEY), {})
    subagents = [r for r in records if r.get("key") != agents.MAIN_KEY]
    running = [r for r in subagents if agents.is_running(r, now)]

    rows = [_main_row(main, running, project, now)]
    for role in (roles.WORKER, roles.TESTER):
        mine = sorted((r for r in subagents if r.get("role") == role), key=lambda r: r.get("started_at", 0))
        active = [r for r in mine if agents.is_running(r, now)]
        if active:
            rows += [_agent_row(r, project, now, role) for r in active]
            continue
        recent = [r for r in mine if now - (r.get("ended_at") or agents.last_activity(r)) < RECENT_DONE_SECONDS]
        rows.append(_agent_row(recent[-1], project, now, role) if recent else Row(role, False, "—"))
    for record in running:
        if record.get("role") == roles.OTHER:
            rows.append(_agent_row(record, project, now, str(record.get("agent_type") or "agent")))
    judges = [r for r in subagents if r.get("role") == "judge"
              and (agents.is_running(r, now) or now - (r.get("ended_at") or 0) < RECENT_DONE_SECONDS)]
    rows += [_agent_row(r, project, now, str(r.get("agent_type") or "judge"))
             for r in sorted(judges, key=lambda r: r.get("key", ""))] or [Row("judge", False, "—")]
    return Board(title, subtitle, rows)


def _fit(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: max(width - 1, 0)] + "…"


def render(board: Board, width: int, color: bool = False) -> str:
    width = max(MIN_WIDTH, min(width, MAX_WIDTH))
    detail_width = width - NAME_WIDTH - STATUS_WIDTH - 4
    head = f"┌ {_fit(board.title, width - 6)} "
    lines = [head + "─" * (width - 1 - len(head)) + "┐",
             f"│ {_fit(board.subtitle, width - 4).ljust(width - 4)} │",
             f"├{'─' * NAME_WIDTH}┬{'─' * STATUS_WIDTH}┬{'─' * detail_width}┤"]
    for row in board.rows:
        status_cell = f"{ACTIVE if row.active else IDLE} {row.status}"
        elapsed = f" {row.elapsed}" if row.elapsed else ""
        detail = _fit(row.detail, detail_width - 2 - len(elapsed)).ljust(detail_width - 2 - len(elapsed))
        lines.append(f"│ {_fit(row.name, NAME_WIDTH - 2).ljust(NAME_WIDTH - 1)}"
                     f"│ {_fit(status_cell, STATUS_WIDTH - 1).ljust(STATUS_WIDTH - 1)}"
                     f"│ {detail}{elapsed} │")
    lines.append(f"└{'─' * NAME_WIDTH}┴{'─' * STATUS_WIDTH}┴{'─' * detail_width}┘")
    text = "\n".join(lines)
    if color:
        text = text.replace(ACTIVE, f"\x1b[32m{ACTIVE}\x1b[0m").replace(IDLE, f"\x1b[2m{IDLE}\x1b[0m")
    return text


def default_session(project: Project) -> str | None:
    """The session worth watching: a live one first, then one with an active
    task, then the most recently active."""
    best: tuple | None = None
    for directory in session.session_dirs(project):
        meta = session.read_meta(directory) or {}
        records = agents.all_records(directory)
        activity = max([meta.get("last_seen_at", 0)] + [agents.last_activity(r) for r in records])
        rank = (session.owner_alive(meta) is True,
                session.active_task(session.read_state(directory)) is not None, activity)
        if best is None or rank > best[0]:
            best = (rank, directory.name)
    return best[1] if best else None


def resolve_session(project: Project, wanted: str | None) -> str | None:
    if not wanted:
        return default_session(project)
    names = [d.name for d in session.session_dirs(project)]
    matches = [n for n in names if n == wanted] or [n for n in names if n.startswith(wanted)]
    return matches[0] if len(matches) == 1 else None


def frame(project: Project, wanted: str | None, color: bool, footer: str = "") -> str:
    session_id = resolve_session(project, wanted)
    width = shutil.get_terminal_size((80, 24)).columns
    text = render(collect(project, session_id), width, color)
    where = f"session {session_id[:8]}" if session_id else "no session yet"
    return f"{text}\n{where}{footer}"


def watch(project: Project, wanted: str | None, interval: float, color: bool,
          frames: int | None = None) -> None:
    """Redraw until interrupted (or for `frames` frames, for tests)."""
    out = sys.stdout
    out.write("\x1b[?25l")  # hide the cursor
    try:
        shown = 0
        while frames is None or shown < frames:
            stamp = time.strftime("%H:%M:%S")
            out.write("\x1b[H\x1b[2J" + frame(project, wanted, color, f" · {stamp} · Ctrl+C to quit") + "\n")
            out.flush()
            shown += 1
            if frames is None or shown < frames:
                time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        out.write("\x1b[?25h\n")
        out.flush()
