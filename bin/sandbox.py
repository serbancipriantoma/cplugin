"""Entry point of the sandbox; .claude/bin/sandbox in a project execs this.

    sandbox [claude arguments...]   start Claude Code in the sandbox (e.g. sandbox --continue)
    sandbox --dry-run               print the command (and the macOS profile), start nothing
"""

import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

if sys.version_info < (3, 11):
    sys.exit(f"foreman needs Python 3.11+, found {sys.version.split()[0]}")

sys.path.insert(0, str(PLUGIN_ROOT))

from foreman import sandbox  # noqa: E402
from foreman.environment import SANDBOX_ENV  # noqa: E402
from foreman.project import Project, find_project_root  # noqa: E402


def main(args: list[str]) -> int:
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    root = find_project_root(os.getcwd())
    if root is None:
        print("error: not inside a foreman project (no .foreman/config.toml found)", file=sys.stderr)
        return 1
    project = Project(root)
    try:
        found = sandbox.check()
        command = sandbox.argv(project, PLUGIN_ROOT, args, found)
    except sandbox.SandboxError as exc:
        print(f"error: {exc}. Refusing to run Claude Code without permission prompts unconfined.",
              file=sys.stderr)
        return 1
    if dry_run:
        if command[0] == "sandbox-exec":  # the profile is long: print it on its own
            print(" ".join(command[:2] + ["<profile>"] + command[3:]))
            print(command[2])
        else:
            print(" ".join(command))
        return 0
    print(sandbox.notice(project, found), file=sys.stderr)
    os.chdir(project.root)
    os.execvpe(command[0], command, {**os.environ, SANDBOX_ENV: "1"})


sys.exit(main(sys.argv[1:]))
