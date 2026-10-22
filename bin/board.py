"""Entry point of the board; .claude/bin/board in a project execs this.

    board                 print the board once
    board --watch         redraw every second until Ctrl+C (run it in a second terminal)
    board --session ID    show a given session (an ID prefix is enough)
"""

import argparse
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

if sys.version_info < (3, 11):
    sys.exit(f"foreman needs Python 3.11+, found {sys.version.split()[0]}")

sys.path.insert(0, str(PLUGIN_ROOT))

from foreman import board  # noqa: E402
from foreman.project import Project, find_project_root  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="board", description="foreman agent board")
    parser.add_argument("--watch", action="store_true", help="redraw until Ctrl+C")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between redraws (default 1)")
    parser.add_argument("--session", help="session ID or prefix (default: the live session)")
    parser.add_argument("--no-color", action="store_true", help="plain text, no ANSI colors")
    args = parser.parse_args(argv)

    root = find_project_root(os.getcwd())
    if root is None:
        print("error: not inside a foreman project (no .foreman/config.toml found)", file=sys.stderr)
        return 1
    project = Project(root)
    color = not args.no_color and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if args.watch:
        board.watch(project, args.session, max(args.interval, 0.2), color)
    else:
        print(board.frame(project, args.session, color))
    return 0


sys.exit(main(sys.argv[1:]))
