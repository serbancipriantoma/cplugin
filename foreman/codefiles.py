"""Which paths count as code, and so need an active task to be edited."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .config import code_extensions, locker_dir

# Never code, even inside bin/ or scripts/.
_DOC_EXTENSIONS = {"md", "txt", "json", "yaml", "yml", "toml", "csv", "png", "jpg", "jpeg",
                   "gif", "svg", "webp", "ico", "lock"}


def is_code_file(rel_path: str, abs_path: Path, cfg: dict) -> bool:
    """`rel_path` is relative to the project root, POSIX separators."""
    path = PurePosixPath(rel_path)
    if path.parts and path.parts[0] == locker_dir(cfg):
        return False  # the locker holds what passes between the user and Claude
    ext = path.suffix.lower().lstrip(".")
    if ext in code_extensions(cfg):
        return True
    if ext in _DOC_EXTENSIONS:
        return False
    code_dirs = set(cfg.get("files", {}).get("code_dirs", []))
    if code_dirs.intersection(path.parts[:-1]):
        return True
    # An existing extensionless script anywhere else.
    if not ext and abs_path.is_file():
        try:
            with open(abs_path, "rb") as fh:
                return fh.read(2) == b"#!"
        except OSError:
            return False
    return False
