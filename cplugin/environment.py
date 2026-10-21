"""What this session can use: the Claude models of the roles, which judge CLIs
are installed and where, whether judges can be sandboxed, and the state of the
memory and the tasks. Shown as a short banner at session start and in full by
`tasks start` / `/cplugin:start`.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import VERSION, gates, judges, mindmap, status
from .project import Project
from .task import Task, list_tasks, read_status


@dataclass(frozen=True)
class SeatStatus:
    provider: str
    model: str
    path: str | None    # where the CLI was found, None when it is not installed


def seat_status(cfg: dict) -> list[SeatStatus]:
    found = []
    for seat in cfg.get("judges", {}).get("seat", []):
        if not isinstance(seat, dict):
            continue
        raw = str(seat.get("provider", ""))
        provider = judges.ALIASES.get(raw, raw)
        executable = judges.EXECUTABLES.get(provider)
        found.append(SeatStatus(provider, str(seat.get("model") or ""),
                                shutil.which(executable) if executable else None))
    return found


def _role_model(cfg: dict, role: str) -> str:
    return str(cfg.get("roles", {}).get(role, {}).get("model") or "inherit")


def _fallback(cfg: dict) -> str:
    if cfg.get("judges", {}).get("fallback") != "claude":
        return "no fallback: reviews fail"
    where = shutil.which("claude")
    return f"claude -p ({judges.FALLBACK_MODEL}), read-only" + ("" if where else " — but `claude` is not on PATH")


def _memory(project: Project) -> str:
    if not project.mind_map.is_file():
        return "MIND_MAP.md is missing: run /cplugin:mindmap"
    text = project.mind_map.read_text(encoding="utf-8", errors="replace").strip()
    if mindmap.is_stub(text):
        return "MIND_MAP.md is still the empty template: run /cplugin:mindmap"
    details = len(list(project.mindmap_dir.glob("**/*.md"))) if project.mindmap_dir.is_dir() else 0
    over = " (over budget: compress it)" if len(text) > mindmap.MIND_MAP_BUDGET else ""
    return (f"MIND_MAP.md {len(text):,} / {mindmap.MIND_MAP_BUDGET:,} characters{over}, "
            f"{details} detail file(s) in {project.mindmap_dir.name}/")


def _task_line(task: Task | None) -> str:
    if task is None:
        return "no active task"
    done, total = gates.progress(task.gates())
    return f"task {task.label} {task.slug} active, gate {min(done + 1, total)}/{total}"


def banner(project: Project, cfg: dict, task: Task | None, sandbox: str) -> str:
    """Two or three short lines for the user at session start."""
    seats = seat_status(cfg)
    installed = [s for s in seats if s.path]
    marks = ", ".join(f"{s.provider} ✓" if s.path else f"{s.provider} ✗ not installed" for s in seats)
    judges_text = marks or "none configured"
    if not installed:
        judges_text += f" → {_fallback(cfg)}"
    lines = [f"cplugin {VERSION} · {_task_line(task)} · {_memory(project)}",
             f"agents: worker {_role_model(cfg, 'worker')} · tester {_role_model(cfg, 'tester')}",
             f"judges: {judges_text}"]
    if installed and sandbox != "ok":
        lines.append(f"warning: judges run without an OS sandbox here ({sandbox}); only the tamper check guards the project")
    lines[-1] += "  (say \"start\" for details)"
    return "\n".join(lines)


def report(project: Project, cfg: dict, plugin_root: Path, session_id: str | None,
           sandbox: str) -> str:
    """The full picture, for `tasks start`."""
    judges_cfg = cfg.get("judges", {})
    lines = [f"cplugin {VERSION} (plugin at {plugin_root})",
             f"project: {project.root.name} ({project.root})", "",
             "Agents (Claude models, used through your Claude account)",
             "  main    this session's model (the one you started Claude Code with)"]
    for role in ("worker", "tester"):
        lines.append(f"  {role:<7} {_role_model(cfg, role):<8} {plugin_root / 'agents' / f'{role}.md'}")

    lines += ["", f"Judges ({judges_cfg.get('mode', 'panel')}, up to {judges_cfg.get('timeout_min', 8)} min each)"]
    seats = seat_status(cfg)
    for seat in seats:
        model = seat.model or "the CLI's default model"
        where = f"✓ {seat.path}" if seat.path else "✗ not installed: this seat is skipped"
        lines.append(f"  {seat.provider:<7} {where} · {model}")
    if not seats:
        lines.append("  (no seats in .cplugin/config.toml)")
    lines.append(f"  fallback when none is installed: {_fallback(cfg)}")
    lines.append("  containment: " + {
        "ok": "sandbox-exec works here: agy and claude run with the project read-only, codex in its own read-only sandbox",
        "nested": "inside another sandbox, sandbox-exec cannot add rules: only the tamper check guards the project",
        "none": "no sandbox-exec on this system: only the tamper check guards the project",
    }[sandbox])

    lines += ["", "Memory", f"  {_memory(project)}", "", "Tasks"]
    active = status.active_task(project, session_id)
    if active is not None:
        lines.append(f"  active: {active.title}. {status.where(project, active)}")
    open_tasks = [t for t in list_tasks(project) if read_status(t) != "done" and t != active]
    for task in open_tasks:
        done, total = gates.progress(task.gates())
        lines.append(f"  {read_status(task):<7} {task.title} ({done}/{total} gates)")
    done_count = sum(1 for t in list_tasks(project) if read_status(t) == "done")
    if active is None and not open_tasks:
        lines.append("  no open tasks")
    if done_count:
        lines.append(f"  done: {done_count}")
    tests = str(cfg.get("tests", {}).get("command") or "")
    lines += ["", f"Tests: {tests or 'tests.command is not set in .cplugin/config.toml'}",
              "Board: run .claude/bin/board --watch in a second terminal"]
    return "\n".join(lines)
