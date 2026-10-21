"""The few git calls cplugin needs."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(root: Path, *args: str, timeout: float = 10) -> bytes | None:
    """stdout of `git -C root <args>`, or None when git fails or is missing."""
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def is_repo(root: Path) -> bool:
    return (git(root, "rev-parse", "--is-inside-work-tree") or b"").strip() == b"true"


def head(root: Path) -> str | None:
    """The HEAD commit, or None outside a repository or before the first commit."""
    out = git(root, "rev-parse", "--verify", "-q", "HEAD")
    return out.decode().strip() if out else None


def git_dir(root: Path) -> Path | None:
    out = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(out.decode().strip()) if out else None
