"""Mechanical project setup behind `tasks init` and /cplugin:init. Idempotent."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import gitutil, wrappers
from .fsutil import write_atomic, write_if_changed
from .project import Project

# Tools that would compete with task.md as the source of truth.
DENIED_TOOLS = ["TodoWrite", "EnterPlanMode"]
# Plugins switched off in cplugin projects, unless the project already decided.
CONFLICTING_PLUGINS = ("playbook",)

BLOCK_BEGIN = "<!-- cplugin:begin"
BLOCK_END = "<!-- cplugin:end -->"
_BLOCK_RE = re.compile(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), re.DOTALL)


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def record(self, outcome: str, item: str) -> None:
        {"created": self.created, "updated": self.updated, "unchanged": self.unchanged}[outcome].append(item)

    def render(self) -> str:
        lines = []
        for label, items in (("created", self.created), ("updated", self.updated),
                             ("unchanged", self.unchanged), ("WARNING", self.warnings)):
            lines += [f"{label}: {item}" for item in items]
        return "\n".join(lines)


def _template(plugin_root: Path, name: str) -> str:
    return (plugin_root / "templates" / name).read_text(encoding="utf-8")


def merge_claude_md(existing: str | None, block: str, project_name: str) -> str:
    """Insert or replace the managed block, leaving everything else untouched."""
    block = block.strip()
    if existing is None:
        return f"# {project_name}\n\n{block}\n"
    if _BLOCK_RE.search(existing):
        return _BLOCK_RE.sub(lambda _: block, existing, count=1)
    return existing.rstrip("\n") + "\n\n" + block + "\n"


def _installed_plugin_keys() -> list[str]:
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        data = json.loads((config_dir / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    plugins = data.get("plugins") if isinstance(data, dict) else None
    return sorted(plugins) if isinstance(plugins, dict) else []


def merge_settings(settings: dict, installed: list[str]) -> dict:
    permissions = settings.setdefault("permissions", {})
    deny = permissions.setdefault("deny", [])
    for tool in DENIED_TOOLS:
        if tool not in deny:
            deny.append(tool)
    for key in installed:
        if key.split("@", 1)[0] in CONFLICTING_PLUGINS:
            settings.setdefault("enabledPlugins", {}).setdefault(key, False)
    return settings


def _rel(project: Project, path: Path) -> str:
    return str(path.relative_to(project.root))


# Settings whose old default a newer version replaced. Init upgrades a value
# only while it still equals the old default, i.e. the user never changed it.
CONFIG_UPGRADES = [
    ("roles.worker", "paths", '["src/**", "app/**"]',
     'paths = ["**"]                      # narrow it (e.g. ["src/**"]) to fence the worker in'),
    ("roles.tester", "paths", '["tests/**", "**/test_*.py", "**/*_test.*", "**/*.test.*", "**/*.spec.*"]',
     'paths = ["tests/**", "test/**", "**/__tests__/**", "**/test_*.py", "**/*_test.*",\n'
     '         "**/*.test.*", "**/*.spec.*"]'),
    ("judges", "timeout_min", "15",
     "timeout_min = 8         # per judge; keep it under 10, the longest a Claude Code command may run"),
]


def upgrade_config(text: str) -> tuple[str, list[str]]:
    """Replace untouched old defaults in config.toml text; comments and every
    other line stay as they are. Returns the new text and the settings changed."""
    changed = []
    for section, key, old_value, new_line in CONFIG_UPGRADES:
        header = re.search(rf"^\[{re.escape(section)}\][ \t]*$", text, re.MULTILINE)
        if not header:
            continue
        following = re.search(r"^\[", text[header.end():], re.MULTILINE)
        end = header.end() + following.start() if following else len(text)
        line = re.compile(rf"^{re.escape(key)}\s*=\s*{re.escape(old_value)}[^\n]*$", re.MULTILINE)
        body, count = line.subn(lambda _: new_line, text[header.end():end], count=1)
        if count:
            text = text[:header.end()] + body + text[end:]
            changed.append(f"{section}.{key}")
    return text, changed


def init_project(root: Path, plugin_root: Path, name: str | None = None) -> Report:
    project = Project(root.resolve())
    name = name or project.root.name
    report = Report()

    for directory in (project.state_dir, project.tasks_dir, project.sessions_dir, project.mindmap_dir):
        if directory.is_dir():
            report.record("unchanged", _rel(project, directory) + "/")
        else:
            directory.mkdir(parents=True)
            report.record("created", _rel(project, directory) + "/")

    # Files the user owns once created: never overwritten.
    for path, content in (
        (project.config_path, _template(plugin_root, "config.toml")),
        (project.state_dir / ".gitignore", "# runtime state, one directory per Claude Code session\nsessions/\n"),
        (project.mind_map, _template(plugin_root, "MIND_MAP.md").replace("{project}", name)),
    ):
        if path.exists():
            report.record("unchanged", _rel(project, path))
        else:
            write_atomic(path, content)
            report.record("created", _rel(project, path))

    config_text = project.config_path.read_text(encoding="utf-8")
    upgraded, settings_changed = upgrade_config(config_text)
    if settings_changed:
        write_atomic(project.config_path, upgraded)
        rel = _rel(project, project.config_path)
        if rel in report.unchanged:
            report.unchanged.remove(rel)
        report.record("updated", f"{rel} (old defaults upgraded: {', '.join(settings_changed)})")

    existing = project.claude_md.read_text(encoding="utf-8") if project.claude_md.is_file() else None
    merged = merge_claude_md(existing, _template(plugin_root, "CLAUDE.md"), name)
    report.record(write_if_changed(project.claude_md, merged), "CLAUDE.md (cplugin block)")

    settings_rel = _rel(project, project.settings_path)
    settings: dict | None = {}
    if project.settings_path.is_file():
        try:
            settings = json.loads(project.settings_path.read_text(encoding="utf-8"))
        except ValueError:
            settings = None
        if not isinstance(settings, dict):
            settings = None
            report.warnings.append(f"{settings_rel} is not a JSON object; left untouched")
    if settings is not None:
        merged_settings = merge_settings(settings, _installed_plugin_keys())
        report.record(write_if_changed(project.settings_path, json.dumps(merged_settings, indent=2) + "\n"),
                      settings_rel)

    for launcher, outcome in wrappers.ensure_launchers(project, plugin_root).items():
        report.record(outcome, f".claude/bin/{launcher}")

    if not gitutil.is_repo(project.root):
        report.warnings.append(
            "not a git repository. cplugin needs git for the Bash write check, the "
            "impl-review diff and the judge tamper guard. Run `git init`."
        )
    return report
