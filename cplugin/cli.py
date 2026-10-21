"""The `tasks` command line. Reached through .claude/bin/tasks in a project."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import VERSION, mindmap
from .init import init_project
from .project import Project, find_project_root


def _cmd_init(args: argparse.Namespace, plugin_root: Path) -> int:
    target = Path(args.dir or os.getcwd()).resolve()
    enclosing = find_project_root(target)
    if args.dir is None and enclosing is not None and enclosing != target:
        print(f"error: {target} is inside the cplugin project at {enclosing}.\n"
              f"Run init there, or pass --dir to create a nested project on purpose.", file=sys.stderr)
        return 1
    report = init_project(target, plugin_root, args.name)
    print(f"cplugin {VERSION} init: {target}")
    print(report.render())
    return 0


def _cmd_context(args: argparse.Namespace, plugin_root: Path) -> int:
    root = find_project_root(os.getcwd())
    if root is None:
        print("error: not inside a cplugin project (no .cplugin/config.toml found)", file=sys.stderr)
        return 1
    print(mindmap.session_context(Project(root)))
    return 0


def _cmd_version(args: argparse.Namespace, plugin_root: Path) -> int:
    print(f"cplugin {VERSION} ({plugin_root})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tasks", description="cplugin task workflow")
    sub = parser.add_subparsers(dest="command", required=True)

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
    return args.func(args, plugin_root)
