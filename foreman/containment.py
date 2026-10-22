"""OS write containment: macOS sandbox-exec or Linux bubblewrap (bwrap).

Two shapes are built from it:
- read-only (judges): the whole file system read-only, except the temp folders
  and the state the agent CLIs keep under the home folder;
- session (the sandbox launcher): the same, plus the project writable, with
  its .git kept read-only so history cannot be rewritten.

Reads and the network stay open in both. When the containment cannot be
applied here, `detect()` says why and what to do, and the callers either
refuse to start (the launcher) or say the judges run unconfined.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import gitutil

SYSTEM_WRITABLE = ("/dev", "/private/tmp", "/private/var/folders", "/tmp", "/var/folders", "/var/tmp")
# Under the home folder: Claude Code's state, the judges' CLIs, and the caches
# and Library folders tools (npm, the macOS keychain, ...) write to.
HOME_WRITABLE = (".claude", ".codex", ".gemini", ".cache", ".local", ".npm", ".config", "Library")
HOME_WRITABLE_FILES = (".claude.json",)

LINUX_HELP = "see docs/linux.md in the foreman repository"


@dataclass(frozen=True)
class Containment:
    tool: str | None    # "sandbox-exec", "bwrap", or None
    state: str          # "ok"; "nested": the OS refuses here; "none": no tool on this system
    hint: str = ""      # what to do when it is not "ok"
    proc: bool = True   # bwrap only: whether a fresh /proc can be mounted

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    def describe(self) -> str:
        if self.ok:
            return f"{self.tool} works here"
        return f"{self.tool or 'no sandbox tool'}: {self.hint}"


def _run(argv: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None


@lru_cache(maxsize=1)
def detect() -> Containment:
    if sys.platform == "darwin":
        if not shutil.which("sandbox-exec"):
            return Containment(None, "none", "sandbox-exec is missing from this macOS")
        probe = '(version 1)(allow default)(deny file-write* (subpath "/foreman-nesting-probe"))'
        out = _run(["sandbox-exec", "-p", probe, "/usr/bin/true"])
        if out is not None and out.returncode == 0:
            return Containment("sandbox-exec", "ok")
        return Containment("sandbox-exec", "nested",
                           "already inside another sandbox, and macOS cannot nest one that adds rules")
    if sys.platform.startswith("linux"):
        if not shutil.which("bwrap"):
            return Containment(None, "none", f"install bubblewrap (e.g. `sudo apt install bubblewrap`); {LINUX_HELP}")
        true = shutil.which("true") or "/bin/true"
        base = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev"]
        # A fresh /proc needs rights some systems withhold; without it /proc comes from the host.
        for proc in (True, False):
            out = _run(base + (["--proc", "/proc"] if proc else []) + [true])
            if out is not None and out.returncode == 0:
                return Containment("bwrap", "ok", proc=proc)
        error = (out.stderr.strip().splitlines() or ["unknown error"])[-1] if out else "did not run"
        return Containment("bwrap", "nested",
                           f"bwrap cannot create its namespace here ({error}): unprivileged user namespaces "
                           f"are blocked, or this is a container; {LINUX_HELP}")
    return Containment(None, "none", f"no supported sandbox on {sys.platform}")


def _home() -> Path:
    return Path.home().resolve()


def _git_dirs(root: Path) -> list[str]:
    dirs = {str(root / ".git")}
    common = gitutil.git_dir(root)
    if common:
        dirs.add(str(common.resolve()))
    return sorted(dirs)


# ── macOS ───────────────────────────────────────────────────────────────────

def _q(path: str) -> str:
    return path.replace("\\", "\\\\").replace('"', '\\"')


def seatbelt_profile(project_root: Path, home: Path | None = None, *, writable: bool = True) -> str:
    """Deny every write but temp and home state; the project is writable or read-only
    as asked, and its .git always read-only. Later rules win in a profile, so the
    denies come last: they hold even for a project that sits inside a temp folder."""
    home = (home or _home()).resolve()
    root = project_root.resolve()
    allowed = [*SYSTEM_WRITABLE, *(str(home / sub) for sub in HOME_WRITABLE)]
    if writable:
        allowed.insert(0, str(root))
    exceptions = "".join(f'\n        (require-not (subpath "{_q(p)}"))' for p in allowed)
    for name in HOME_WRITABLE_FILES:  # a prefix match also covers the backups written next to them
        escaped = name.replace(".", "\\.")
        exceptions += f'\n        (require-not (regex #"^{_q(str(home))}/{escaped}"))'
    lines = ["(version 1)", "(allow default)", f"(deny file-write*\n    (require-all{exceptions}))"]
    denied = _git_dirs(root) if writable else [str(root), *_git_dirs(root)]
    lines += [f'(deny file-write* (subpath "{_q(d)}"))' for d in denied]
    return "\n".join(lines)


# ── Linux ───────────────────────────────────────────────────────────────────

def bwrap_argv(project_root: Path, inner: list[str], *, writable: bool = True, proc: bool = True,
               interactive: bool = False, home: Path | None = None) -> list[str]:
    """Read-only root, writable temp and home state, then the project writable or
    read-only as asked and its .git read-only. Later mounts override earlier ones,
    so this holds even for a project inside a temp folder."""
    home = (home or _home()).resolve()
    argv = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev"]
    if proc:
        argv += ["--proc", "/proc"]
    allowed = [p for p in SYSTEM_WRITABLE if p != "/dev"]
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir:
        allowed.append(tmpdir)
    runtime = os.environ.get("XDG_RUNTIME_DIR")  # per-user sockets (dbus, keyring)
    if runtime:
        allowed.append(runtime)
    allowed += [str(home / sub) for sub in (*HOME_WRITABLE, *HOME_WRITABLE_FILES)]
    for path in dict.fromkeys(allowed):
        if os.path.exists(path) and not os.path.islink(path):
            argv += ["--bind", path, path]
    root = str(project_root.resolve())
    argv += ["--bind" if writable else "--ro-bind", root, root]
    for git in _git_dirs(project_root.resolve()):
        if os.path.exists(git):
            argv += ["--ro-bind", git, git]
    argv.append("--die-with-parent")
    if not interactive:
        argv.append("--new-session")  # no terminal to inject keystrokes into
    return argv + ["--", *inner]


# ── both ────────────────────────────────────────────────────────────────────

def wrap_read_only(project_root: Path, inner: list[str], found: Containment | None = None) -> list[str] | None:
    """`inner` with the project read-only and only temp and home state writable (for
    judges); None when no containment is available."""
    c = found or detect()
    if not c.ok:
        return None
    if c.tool == "sandbox-exec":
        return ["sandbox-exec", "-p", seatbelt_profile(project_root, writable=False), *inner]
    return bwrap_argv(project_root, inner, writable=False, proc=c.proc)


def wrap_session(project_root: Path, inner: list[str], found: Containment | None = None) -> list[str] | None:
    """`inner` able to write the project (not .git), temp and home state (for the launcher)."""
    c = found or detect()
    if not c.ok:
        return None
    if c.tool == "sandbox-exec":
        return ["sandbox-exec", "-p", seatbelt_profile(project_root), *inner]
    return bwrap_argv(project_root, inner, proc=c.proc, interactive=True)
