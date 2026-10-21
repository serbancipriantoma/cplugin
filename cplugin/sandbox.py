"""Running Claude Code without permission prompts, inside OS write containment.

`.claude/bin/sandbox` starts `claude --dangerously-skip-permissions` under
macOS sandbox-exec with a profile that denies every file write except:
the project (but not its .git, so history cannot be rewritten), the system's
temporary directories and devices, and the home directories Claude Code and
its tools keep state and caches in. Reads and the network stay open. When the
containment cannot be applied, it refuses to start instead of running
unconfined.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import gitutil, judges
from .environment import SANDBOX_ENV
from .project import Project

SYSTEM_WRITABLE = ("/dev", "/private/tmp", "/private/var/folders", "/tmp", "/var/folders")
# Under the home directory: Claude Code's state, the judges' CLIs, and the
# caches and Library folders tools (npm, keychain refresh, ...) write to.
HOME_WRITABLE = (".claude", ".codex", ".gemini", ".cache", ".local", ".npm", ".config", "Library")


class SandboxError(Exception):
    pass


def _quote(path: str) -> str:
    return path.replace("\\", "\\\\").replace('"', '\\"')


def profile(project: Project, home: Path | None = None) -> str:
    home = (home or Path.home()).resolve()
    root = project.root.resolve()
    writable = [str(root), *SYSTEM_WRITABLE, *(str(home / sub) for sub in HOME_WRITABLE)]
    exceptions = "".join(f'\n        (require-not (subpath "{_quote(p)}"))' for p in writable)
    # ~/.claude.json and its backups sit next to ~/.claude, not inside it.
    exceptions += f'\n        (require-not (regex #"^{_quote(str(home))}/\\.claude\\.json"))'
    lines = ["(version 1)", "(allow default)",
             f"(deny file-write*\n    (require-all{exceptions}))"]
    git_dirs = {str(root / ".git")}
    common = gitutil.git_dir(root)
    if common:
        git_dirs.add(str(common.resolve()))
    lines += [f'(deny file-write* (subpath "{_quote(d)}"))' for d in sorted(git_dirs)]
    return "\n".join(lines)


def plugin_installed(plugin_root: Path) -> bool:
    """True for a copy installed by Claude Code, False for a checkout loaded with --plugin-dir."""
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        plugin_root.resolve().relative_to((config_dir / "plugins").resolve())
    except ValueError:
        return False
    return True


def check() -> None:
    """Raise SandboxError when the containment cannot be applied here."""
    if os.environ.get(SANDBOX_ENV):
        raise SandboxError("this shell is already inside the cplugin sandbox")
    if sys.platform != "darwin":
        raise SandboxError("the sandbox needs macOS sandbox-exec; other systems are not supported yet")
    state = judges.seatbelt_status()
    if state == "none":
        raise SandboxError("sandbox-exec is not available")
    if state == "nested":
        raise SandboxError("this process is already inside another sandbox, and macOS cannot nest one "
                           "that adds rules; start the sandbox from a plain terminal")


def argv(project: Project, plugin_root: Path, extra: list[str]) -> list[str]:
    claude = shutil.which("claude")
    if claude is None:
        raise SandboxError("`claude` is not on PATH")
    plugin = [] if plugin_installed(plugin_root) else ["--plugin-dir", str(plugin_root)]
    return ["sandbox-exec", "-p", profile(project), claude, "--dangerously-skip-permissions",
            *plugin, *extra]


def notice(project: Project) -> str:
    return (f"cplugin sandbox: Claude Code without permission prompts. It can write only in "
            f"{project.root} (not .git), the temp folders, and Claude's and its tools' own state "
            f"under your home folder. Everything else is read-only. Exit Claude Code to leave.")
