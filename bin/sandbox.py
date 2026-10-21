"""Entry point of the sandbox; .claude/bin/sandbox in a project execs this.

    sandbox [claude arguments...]   start Claude Code in the sandbox (e.g. sandbox --continue)
    sandbox --dry-run               print the command and the profile, start nothing
"""

import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

if sys.version_info < (3, 11):
    sys.exit(f"cplugin needs Python 3.11+, found {sys.version.split()[0]}")

sys.path.insert(0, str(PLUGIN_ROOT))

from cplugin import sandbox  # noqa: E402
from cplugin.environment import SANDBOX_ENV  # noqa: E402
from cplugin.project import Project, find_project_root  # noqa: E402


def main(args: list[str]) -> int:
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    root = find_project_root(os.getcwd())
    if root is None:
        print("error: not inside a cplugin project (no .cplugin/config.toml found)", file=sys.stderr)
        return 1
    project = Project(root)
    try:
        sandbox.check()
        command = sandbox.argv(project, PLUGIN_ROOT, args)
    except sandbox.SandboxError as exc:
        print(f"error: {exc}. Refusing to run Claude Code without permission prompts unconfined.",
              file=sys.stderr)
        return 1
    if dry_run:
        print(" ".join(command[:2] + ["<profile>"] + command[3:]))
        print(command[2])
        return 0
    print(sandbox.notice(project), file=sys.stderr)
    os.chdir(project.root)
    os.execvpe(command[0], command, {**os.environ, SANDBOX_ENV: "1"})


sys.exit(main(sys.argv[1:]))
