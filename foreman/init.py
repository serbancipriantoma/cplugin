"""Mechanical project setup behind `tasks init` and /foreman:init. Idempotent."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config, gitutil, wrappers
from .fsutil import write_atomic, write_if_changed
from .project import LEGACY_STATE_DIR, STATE_DIR, Project

# Tools that would compete with task.md as the source of truth.
DENIED_TOOLS = ["TodoWrite", "EnterPlanMode"]
# Plugins switched off in foreman projects, unless the project already decided.
CONFLICTING_PLUGINS = ("playbook",)
# Set in the personal settings.local.json, unless the project already has a status line.
STATUS_LINE = {"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/bin/statusline', "padding": 0}
# The locker's own .gitignore: the first line marks the folder as foreman's.
LOCKER_MARKER = "# foreman's locker"
LOCKER_GITIGNORE = (f"{LOCKER_MARKER}: what passes between you and Claude, never committed.\n"
                    "# Delete this file and the folder is an ordinary one again.\n*\n")

BLOCK_BEGIN = "<!-- foreman:begin"
BLOCK_END = "<!-- foreman:end -->"
_BLOCK_RE = re.compile(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), re.DOTALL)
# The block as written before the plugin was named foreman.
_LEGACY_BLOCK_RE = re.compile(r"<!-- cplugin:begin.*?<!-- cplugin:end -->", re.DOTALL)


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
    for pattern in (_BLOCK_RE, _LEGACY_BLOCK_RE):
        if pattern.search(existing):
            return pattern.sub(lambda _: block, existing, count=1)
    return existing.rstrip("\n") + "\n\n" + block + "\n"


def _claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _installed_plugin_keys() -> list[str]:
    try:
        data = json.loads((_claude_config_dir() / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    plugins = data.get("plugins") if isinstance(data, dict) else None
    return sorted(plugins) if isinstance(plugins, dict) else []


def _user_has_status_line() -> bool:
    try:
        data = json.loads((_claude_config_dir() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and "statusLine" in data


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


def _read_settings(project: Project, path: Path, report: Report) -> dict | None:
    """{} for a missing file; None, with a warning, for one that is not a JSON object."""
    if not path.is_file():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        settings = None
    if not isinstance(settings, dict):
        report.warnings.append(f"{_rel(project, path)} is not a JSON object; left untouched")
        return None
    return settings


def _ensure_locker(project: Project, name: str | None, report: Report) -> None:
    """Make `name` the locker: a folder whose own .gitignore keeps all of it out
    of git. A folder that is the project's (tracked, or with a .gitignore that is
    not foreman's) is left alone."""
    if name is None:
        report.warnings.append("locker.dir in .foreman/config.toml is not a usable folder name; no locker set up")
        return
    folder = project.root / name
    ignore = folder / ".gitignore"
    label = f"{name}/ (the locker: not in git, for what passes between you and Claude)"
    ours = ignore.is_file() and ignore.read_text(encoding="utf-8").startswith(LOCKER_MARKER)
    tracked = (gitutil.git(project.root, "ls-files", "--", name) or b"").strip()
    if not ours and ((folder.exists() and not folder.is_dir()) or ignore.exists() or tracked):
        report.warnings.append(f"{name} is the project's own (tracked by git, or not a foreman locker), so it "
                               f"was left alone; name another folder with [locker] dir in .foreman/config.toml")
        return
    folder.mkdir(exist_ok=True)
    report.record(write_if_changed(ignore, LOCKER_GITIGNORE), label)


def _set_status_line(project: Project, shared: dict | None, report: Report) -> None:
    """Point the personal settings.local.json at foreman's status line, unless
    either project settings file already sets one, and keep that file out of git."""
    path = project.local_settings_path
    rel = _rel(project, path)
    local = _read_settings(project, path, report)
    if local is None or shared is None:
        return
    if local.get("statusLine") == STATUS_LINE:
        report.record("unchanged", f"{rel} (foreman's statusLine)")
    elif "statusLine" in shared or "statusLine" in local:
        report.record("unchanged", "statusLine (the project sets its own; foreman's is not used)")
    else:
        local["statusLine"] = STATUS_LINE
        note = "statusLine: foreman's status line"
        if _user_has_status_line():
            note += "; in this project it replaces the one in ~/.claude/settings.json"
        report.record(write_if_changed(path, json.dumps(local, indent=2) + "\n"), f"{rel} ({note})")

    if (path.is_file() and gitutil.is_repo(project.root)
            and gitutil.git(project.root, "check-ignore", "-q", rel) is None):
        gitignore = project.root / ".claude" / ".gitignore"
        existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
        if path.name not in existing.splitlines():
            head = existing.rstrip("\n") + "\n" if existing else "# personal Claude Code settings, never committed\n"
            report.record(write_if_changed(gitignore, f"{head}{path.name}\n"),
                          f"{_rel(project, gitignore)} (keeps {path.name} out of git)")


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

    legacy = project.root / LEGACY_STATE_DIR
    if legacy.is_dir() and not project.state_dir.exists():
        os.rename(legacy, project.state_dir)
        report.record("updated", f"{LEGACY_STATE_DIR}/ moved to {STATE_DIR}/ (the plugin is now named foreman)")

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

    locker = config.locker_dir(config.load_or_defaults(project, report.warnings))
    _ensure_locker(project, locker, report)

    existing = project.claude_md.read_text(encoding="utf-8") if project.claude_md.is_file() else None
    block = _template(plugin_root, "CLAUDE.md").replace("{locker}", locker or config.DEFAULTS["locker"]["dir"])
    merged = merge_claude_md(existing, block, name)
    report.record(write_if_changed(project.claude_md, merged), "CLAUDE.md (foreman block)")

    settings = _read_settings(project, project.settings_path, report)
    if settings is not None:
        merged_settings = merge_settings(settings, _installed_plugin_keys())
        report.record(write_if_changed(project.settings_path, json.dumps(merged_settings, indent=2) + "\n"),
                      _rel(project, project.settings_path))
    _set_status_line(project, settings, report)

    for launcher, outcome in wrappers.ensure_launchers(project, plugin_root).items():
        report.record(outcome, f".claude/bin/{launcher}")

    if not gitutil.is_repo(project.root):
        report.warnings.append(
            "not a git repository. foreman needs git for the Bash write check, the "
            "impl-review diff and the judge tamper guard. Run `git init`."
        )
    return report
