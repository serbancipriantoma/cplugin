"""Running Claude Code without permission prompts, inside OS write containment.

`.claude/bin/sandbox` starts `claude --dangerously-skip-permissions` under
macOS sandbox-exec or Linux bubblewrap (see foreman.containment): it can write
the project (but not its .git, so history cannot be rewritten), the temp
folders, and the state Claude Code and its tools keep under the home folder.
Everything else is read-only; reads and the network stay open. When the
containment cannot be applied, it refuses to start instead of running
unconfined.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import containment
from .environment import SANDBOX_ENV
from .project import Project


class SandboxError(Exception):
    pass


def plugin_installed(plugin_root: Path) -> bool:
    """True for a copy installed by Claude Code, False for a checkout loaded with --plugin-dir."""
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        plugin_root.resolve().relative_to((config_dir / "plugins").resolve())
    except ValueError:
        return False
    return True


def check() -> containment.Containment:
    """The containment to use; SandboxError when it cannot be applied here."""
    if os.environ.get(SANDBOX_ENV):
        raise SandboxError("this shell is already inside the foreman sandbox")
    found = containment.detect()
    if not found.ok:
        raise SandboxError(found.hint)
    return found


def argv(project: Project, plugin_root: Path, extra: list[str],
         found: containment.Containment | None = None) -> list[str]:
    claude = shutil.which("claude")
    if claude is None:
        raise SandboxError("`claude` is not on PATH")
    plugin = [] if plugin_installed(plugin_root) else ["--plugin-dir", str(plugin_root)]
    command = containment.wrap_session(project.root, [claude, "--dangerously-skip-permissions", *plugin, *extra],
                                       found)
    if command is None:
        raise SandboxError(containment.detect().hint)
    return command


def notice(project: Project, found: containment.Containment) -> str:
    return (f"foreman sandbox ({found.tool}): Claude Code without permission prompts. It can write only "
            f"in {project.root} (not .git), the temp folders, and Claude's and its tools' own state "
            f"under your home folder. Everything else is read-only. Exit Claude Code to leave.")
