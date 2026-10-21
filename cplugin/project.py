"""Project discovery and the fixed layout of a cplugin project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

STATE_DIR = ".cplugin"
CONFIG_FILE = "config.toml"
MIND_MAP_FILE = "MIND_MAP.md"
MINDMAP_DIR = "mindmap"


def find_project_root(start: str | Path) -> Path | None:
    """Walk up from `start` to the first directory holding .cplugin/config.toml."""
    path = Path(start).resolve()
    for directory in (path, *path.parents):
        if (directory / STATE_DIR / CONFIG_FILE).is_file():
            return directory
    return None


@dataclass(frozen=True)
class Project:
    root: Path

    @property
    def state_dir(self) -> Path:
        return self.root / STATE_DIR

    @property
    def config_path(self) -> Path:
        return self.state_dir / CONFIG_FILE

    @property
    def tasks_dir(self) -> Path:
        return self.state_dir / "tasks"

    @property
    def sessions_dir(self) -> Path:
        return self.state_dir / "sessions"

    @property
    def mind_map(self) -> Path:
        return self.root / MIND_MAP_FILE

    @property
    def mindmap_dir(self) -> Path:
        return self.root / MINDMAP_DIR

    @property
    def bin_dir(self) -> Path:
        return self.root / ".claude" / "bin"

    @property
    def claude_md(self) -> Path:
        return self.root / "CLAUDE.md"

    @property
    def settings_path(self) -> Path:
        return self.root / ".claude" / "settings.json"
