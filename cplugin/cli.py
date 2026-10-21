"""The `tasks` command line. Reached through .claude/bin/tasks in a project."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import VERSION, config, gates, mindmap, session
from .init import init_project
from .project import Project, find_project_root
from .status import active_task as _active, task_summary, where as _where
from .task import TASK_TYPES, Task, TaskError, create, find_task, list_tasks, parse_number, \
    read_status, set_status, work_plan_gates


class CliError(Exception):
    pass


def _project() -> Project:
    root = find_project_root(os.getcwd())
    if root is None:
        raise CliError("not inside a cplugin project (no .cplugin/config.toml found). Run /cplugin:init first.")
    return Project(root)


def _session(project: Project) -> str:
    session_id = session.resolve_cli_session(project)
    if session_id is None:
        raise CliError("cannot tell which Claude Code session this is. Run this command from "
                       "inside Claude Code, in a session started after /cplugin:init.")
    return session_id


def _task(project: Project, raw: str) -> Task:
    task = find_task(project, parse_number(raw))
    if task is None:
        raise CliError(f"no task {raw}. See `tasks list`.")
    return task


def _read_request(raw: str | None) -> str:
    if raw == "-":
        return sys.stdin.read()
    return raw or ""


def _cmd_new(args: argparse.Namespace, plugin_root: Path) -> int:
    project = _project()
    cfg = config.load(project)
    task, warnings = create(project, plugin_root, args.type, args.name, args.module or [],
                            _read_request(args.request), bool(cfg["workflow"]["tests_first"]))
    print(f"Created task {task.label}: {task.path.relative_to(project.root)}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    print(f"Next: `.claude/bin/tasks work {task.num}`, then work the Design gates.")
    return 0


def _cmd_work(args: argparse.Namespace, plugin_root: Path) -> int:
    project = _project()
    session_id = _session(project)
    task = _task(project, args.number)
    status = read_status(task)
    if status == "done":
        raise CliError(f"task {task.label} is done. Create a new task for further work.")
    directory = session.session_dir(project, session_id)
    state = session.read_state(directory)
    previous = session.active_task(state)
    if previous and previous != task.num and (old := find_task(project, previous)):
        set_status(old, "paused")
        print(f"Paused task {old.label}.")
    others = session.live_sessions_with_task(project, task.num, exclude=session_id)
    if others:
        print(f"WARNING: task {task.label} is also active in another live session ({', '.join(others)}).")
    session.write_state(directory, {**state, "task": task.num, "pause": None})
    set_status(task, "active")
    print(f"Active task: {task.title}")
    print(_where(project, task))
    return 0


def _cmd_stop(args: argparse.Namespace, plugin_root: Path) -> int:
    project = _project()
    session_id = _session(project)
    task = _active(project, session_id)
    if task is None:
        print("No active task.")
        return 0
    directory = session.session_dir(project, session_id)
    session.write_state(directory, {**session.read_state(directory), "task": None, "pause": None})
    set_status(task, "paused")
    print(f"Deactivated task {task.label} (paused). Resume it with `tasks work {task.num}`.")
    return 0


def _cmd_done(args: argparse.Namespace, plugin_root: Path) -> int:
    project = _project()
    session_id = _session(project)
    task = _active(project, session_id)
    if task is None:
        raise CliError("no active task.")
    all_gates = task.gates()
    still_open = [g for g in all_gates if not g.checked]
    if still_open:
        lines = "\n".join(f"  {task.path.name}:{g.line} {g.text}" for g in still_open[:5])
        more = f"\n  ... and {len(still_open) - 5} more" if len(still_open) > 5 else ""
        raise CliError(f"task {task.label} has {len(still_open)} unchecked gate(s):\n{lines}{more}")
    if not work_plan_gates(task):
        raise CliError(f"task {task.label} has no gates in its Work Plan. Write the steps before closing it.")
    directory = session.session_dir(project, session_id)
    session.write_state(directory, {**session.read_state(directory), "task": None, "pause": None})
    set_status(task, "done")
    print(f"Task {task.label} is done.")
    return 0


def _cmd_status(args: argparse.Namespace, plugin_root: Path) -> int:
    project = _project()
    session_id = session.resolve_cli_session(project)
    task = _active(project, session_id)
    if task is None:
        print("No active task in this session.")
        return 0
    print(f"Active task: {task.title}")
    print(_where(project, task))
    pause = session.read_state(session.session_dir(project, session_id)).get("pause")
    if pause:
        print(f"Paused for the user: {pause}")
    return 0


def _cmd_list(args: argparse.Namespace, plugin_root: Path) -> int:
    project = _project()
    tasks = list_tasks(project)
    if not tasks:
        print("No tasks yet. Create one with `tasks new <type> <name>`.")
        return 0
    for task in tasks:
        done, total = gates.progress(task.gates())
        print(f"{task.label}  {read_status(task):<8} {done:>3}/{total:<3} {task.type:<9} {task.slug}")
    return 0


def _cmd_pause(args: argparse.Namespace, plugin_root: Path) -> int:
    project = _project()
    session_id = _session(project)
    task = _active(project, session_id)
    if task is None:
        raise CliError("no active task.")
    reason = " ".join(args.reason).strip()
    if not reason:
        raise CliError("say why you need the user, e.g. `tasks pause \"which faction goes first?\"`")
    directory = session.session_dir(project, session_id)
    session.write_state(directory, {**session.read_state(directory), "pause": reason})
    print(f"OK: you may end this turn with gates open. Ask the user: {reason}")
    return 0


def _cmd_review(args: argparse.Namespace, plugin_root: Path) -> int:
    _task(_project(), args.number)
    print(f"Judges are not available yet (they arrive in milestone 5). Write "
          f"\"skipped: judges not available yet\" on this gate and on its triage gate, then go on.")
    return 0


def _cmd_init(args: argparse.Namespace, plugin_root: Path) -> int:
    target = Path(args.dir or os.getcwd()).resolve()
    enclosing = find_project_root(target)
    if args.dir is None and enclosing is not None and enclosing != target:
        raise CliError(f"{target} is inside the cplugin project at {enclosing}.\n"
                       f"Run init there, or pass --dir to create a nested project on purpose.")
    report = init_project(target, plugin_root, args.name)
    print(f"cplugin {VERSION} init: {target}")
    print(report.render())
    return 0


def _cmd_context(args: argparse.Namespace, plugin_root: Path) -> int:
    project = _project()
    session_id = session.resolve_cli_session(project)
    task = _active(project, session_id)
    print(mindmap.session_context(project, task_summary=task_summary(project, task)))
    return 0


def _cmd_version(args: argparse.Namespace, plugin_root: Path) -> int:
    print(f"cplugin {VERSION} ({plugin_root})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tasks", description="cplugin task workflow")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p = sub.add_parser("new", help="create a task")
    p.add_argument("type", choices=TASK_TYPES)
    p.add_argument("name", help="short kebab-case name, e.g. knight-damage")
    p.add_argument("--module", action="append", help="module it touches (mindmap/<module>.md); repeatable")
    p.add_argument("--request", help="the user's request, verbatim; '-' reads it from stdin")
    p.set_defaults(func=_cmd_new)

    p = sub.add_parser("work", help="activate a task in this session")
    p.add_argument("number")
    p.set_defaults(func=_cmd_work)

    p = sub.add_parser("stop", help="deactivate the active task without closing it")
    p.set_defaults(func=_cmd_stop)

    p = sub.add_parser("done", help="close the active task (all gates must be checked)")
    p.set_defaults(func=_cmd_done)

    p = sub.add_parser("status", help="the active task and its next gate")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("list", help="all tasks with status and progress")
    p.set_defaults(func=_cmd_list)

    p = sub.add_parser("pause", help="end the turn with gates open because the user is needed")
    p.add_argument("reason", nargs="+")
    p.set_defaults(func=_cmd_pause)

    for name in ("plan-review", "impl-review"):
        p = sub.add_parser(name, help="run the judges (milestone 5)")
        p.add_argument("number")
        p.set_defaults(func=_cmd_review)

    p = sub.add_parser("init", help="set up or upgrade the current directory as a cplugin project")
    p.add_argument("--name", help="project name (default: directory name)")
    p.add_argument("--dir", help="project directory (default: current directory)")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("context", help="print what SessionStart loads into context")
    p.set_defaults(func=_cmd_context)

    p = sub.add_parser("version", help="print the plugin version and location")
    p.set_defaults(func=_cmd_version)
    return parser


def main(argv: list[str], plugin_root: Path) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, plugin_root)
    except (CliError, TaskError, config.ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
