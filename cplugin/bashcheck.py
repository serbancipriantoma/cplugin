"""Catching files a role changed through Bash, where no path check can run first.

PreToolUse snapshots `git status` (every changed or untracked path, with its
mtime and size); PostToolUse takes it again and compares. Paths that changed in
between, minus those written by Edit/Write in the meantime (another agent
working in parallel), are what the Bash command touched. Ignored files never
show up, so build output and caches do not count.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from .fsutil import write_atomic

SNAPSHOT_DIR = "bash"
WRITES_LOG = "writes.log"
MAX_LOG_LINES = 400

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
Snapshot = dict[str, list[int]]


def _git(root: Path, *args: str) -> bytes | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def take(root: Path) -> Snapshot | None:
    """{path: [mtime_ns, size]} for every path under `root` that git reports as
    changed or new, relative to `root`; [-1, -1] for deleted ones. None outside
    a git repository."""
    top = _git(root, "rev-parse", "--show-toplevel")
    status = _git(root, "status", "--porcelain=v1", "-z", "-uall", "--", ".")
    if top is None or status is None:
        return None
    # git reports paths from the repository root, which may sit above the project.
    repo_root = Path(top.decode().strip()).resolve()
    try:
        prefix = root.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return None
    prefix = "" if prefix == "." else prefix + "/"
    entries = status.decode("utf-8", "surrogateescape").split("\0")
    snap: Snapshot = {}
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            i += 1  # the rename source follows as its own entry
        if not path.startswith(prefix):
            continue
        rel = path[len(prefix):]
        try:
            st = os.stat(root / rel)
            snap[rel] = [st.st_mtime_ns, st.st_size]
        except OSError:
            snap[rel] = [-1, -1]
    return snap


def changed(before: Snapshot, after: Snapshot) -> list[str]:
    paths = set(before) | set(after)
    return sorted(p for p in paths if before.get(p) != after.get(p))


def _snapshot_path(session_dir: Path, tool_use_id: str) -> Path | None:
    if not _ID_RE.match(tool_use_id or ""):
        return None
    return session_dir / SNAPSHOT_DIR / f"{tool_use_id}.json"


def save(session_dir: Path, tool_use_id: str, snap: Snapshot) -> None:
    path = _snapshot_path(session_dir, tool_use_id)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, json.dumps(snap))


def pop(session_dir: Path, tool_use_id: str) -> Snapshot | None:
    path = _snapshot_path(session_dir, tool_use_id)
    if path is None:
        return None
    try:
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    path.unlink(missing_ok=True)
    return snap if isinstance(snap, dict) else None


def log_tool_write(session_dir: Path, rel: str, abs_path: Path) -> None:
    """Remember a file written by Edit/Write, so a parallel Bash check skips it."""
    try:
        mtime = os.stat(abs_path).st_mtime_ns
    except OSError:
        return
    log = session_dir / WRITES_LOG
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(f"{mtime}\t{rel}\n")
    lines = log.read_text(encoding="utf-8").splitlines()
    if len(lines) > MAX_LOG_LINES:
        write_atomic(log, "\n".join(lines[-MAX_LOG_LINES // 2:]) + "\n")


def tool_written(session_dir: Path) -> set[tuple[str, int]]:
    try:
        lines = (session_dir / WRITES_LOG).read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    found = set()
    for line in lines:
        mtime, _, rel = line.partition("\t")
        if mtime.isdigit():
            found.add((rel, int(mtime)))
    return found


def bash_changes(session_dir: Path, root: Path, before: Snapshot) -> list[str]:
    after = take(root)
    if after is None:
        return []
    by_tools = tool_written(session_dir)
    return [p for p in changed(before, after)
            if (p, (after.get(p) or [-1])[0]) not in by_tools]
