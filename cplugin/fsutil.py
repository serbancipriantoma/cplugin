"""Small filesystem helpers shared by init, hooks and the CLI."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, content: str, mode: int | None = None) -> None:
    """Write via a temp file in the same directory and rename over the target,
    so a reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_if_changed(path: Path, content: str, mode: int | None = None) -> str:
    """Write `content` unless the file already holds it.
    Returns "created", "updated" or "unchanged"."""
    if path.is_file():
        if path.read_text(encoding="utf-8") == content:
            if mode is not None and (path.stat().st_mode & 0o777) != mode:
                os.chmod(path, mode)
                return "updated"
            return "unchanged"
        write_atomic(path, content, mode)
        return "updated"
    write_atomic(path, content, mode)
    return "created"
