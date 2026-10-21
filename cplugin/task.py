"""Tasks: .cplugin/tasks/<NNN>-<type>-<slug>/task.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import gates
from .fsutil import write_atomic
from .project import MINDMAP_DIR, Project

TASK_TYPES = ("feature", "bugfix", "refactor", "explore", "test", "docs")
STATUSES = ("pending", "active", "paused", "done")
TASK_FILE = "task.md"
MAX_SLUG = 48

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DIR_RE = re.compile(r"^(\d{3,})-([a-z]+)-([a-z0-9-]+)$")
TASK_PATH_RE = re.compile(r"(^|/)\.cplugin/tasks/([^/]+)/task\.md$")
_STATUS_RE = re.compile(r"(^## Status[ \t]*\n+)([^\n]*)", re.MULTILINE)


class TaskError(Exception):
    pass


@dataclass(frozen=True)
class Task:
    num: int
    type: str
    slug: str
    dir: Path

    @property
    def path(self) -> Path:
        return self.dir / TASK_FILE

    @property
    def label(self) -> str:
        return f"{self.num:03d}"

    @property
    def title(self) -> str:
        return f"{self.label} {self.type} {self.slug}"

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def gates(self) -> list[gates.Gate]:
        return gates.parse(self.text())


def parse_dir_name(name: str) -> tuple[int, str, str] | None:
    match = _DIR_RE.match(name)
    if not match:
        return None
    return int(match.group(1)), match.group(2), match.group(3)


def list_tasks(project: Project) -> list[Task]:
    tasks = []
    if project.tasks_dir.is_dir():
        for entry in project.tasks_dir.iterdir():
            parsed = parse_dir_name(entry.name)
            if parsed and (entry / TASK_FILE).is_file() and not entry.is_symlink():
                tasks.append(Task(*parsed, entry))
    return sorted(tasks, key=lambda t: t.num)


def find_task(project: Project, num: int) -> Task | None:
    return next((t for t in list_tasks(project) if t.num == num), None)


def parse_number(raw: str) -> int:
    if not raw.isdigit() or int(raw) <= 0:
        raise TaskError(f"not a task number: {raw!r}")
    return int(raw)


def next_number(project: Project) -> int:
    numbers = []
    if project.tasks_dir.is_dir():
        numbers = [p[0] for e in project.tasks_dir.iterdir() if (p := parse_dir_name(e.name))]
    return max(numbers, default=0) + 1


def read_status(task: Task) -> str:
    match = _STATUS_RE.search(task.text())
    return match.group(2).strip() if match else "unknown"


def set_status(task: Task, status: str) -> None:
    text = task.text()
    if _STATUS_RE.search(text):
        text = _STATUS_RE.sub(lambda m: m.group(1) + status, text, count=1)
    write_atomic(task.path, text)


def _module_context(project: Project, modules: list[str]) -> tuple[list[str], list[str]]:
    """Context lines for each module, plus warnings for modules without a detail file."""
    mind_map = project.mind_map.read_text(encoding="utf-8") if project.mind_map.is_file() else ""
    lines, warnings = [], []
    for module in modules:
        rel = f"{MINDMAP_DIR}/{module}.md"
        node = re.search(rf"^## (\[\d+\][^\n]*?)\s*→\s*{re.escape(rel)}\s*$", mind_map, re.MULTILINE)
        exists = (project.root / rel).is_file()
        label = f"MIND_MAP {node.group(1).strip()} → " if node else ""
        lines.append(f"- {label}`{rel}`" + ("" if exists else " (missing)"))
        if not exists:
            warnings.append(f"{rel} does not exist")
    if not lines:
        lines.append("- (no module given: list the MIND_MAP nodes and detail files this task touches)")
    return lines, warnings


def create(project: Project, plugin_root: Path, task_type: str, slug: str,
           modules: list[str], request: str, tests_first: bool) -> tuple[Task, list[str]]:
    if task_type not in TASK_TYPES:
        raise TaskError(f"unknown task type {task_type!r}; use one of: {', '.join(TASK_TYPES)}")
    if not _SLUG_RE.match(slug) or len(slug) > MAX_SLUG:
        raise TaskError(f"bad task name {slug!r}: use lowercase words joined by '-', at most {MAX_SLUG} characters")
    for module in modules:
        if not _SLUG_RE.match(module):
            raise TaskError(f"bad module name {module!r}: use the detail file's name, e.g. 'combat' for mindmap/combat.md")

    warnings: list[str] = []
    context, module_warnings = _module_context(project, modules)
    warnings += module_warnings
    request = request.strip()
    if not request:
        request = "(missing: paste the user's request here, verbatim)"
        warnings.append("no request given; paste the user's request verbatim into the Request section")

    templates = plugin_root / "templates"
    shape = (templates / ("step-tests-first.md" if tests_first else "step-parallel.md")).read_text(encoding="utf-8")
    num = next_number(project)
    text = (templates / TASK_FILE).read_text(encoding="utf-8")
    for key, value in (("num", f"{num:03d}"), ("n", str(num)), ("type", task_type), ("slug", slug),
                       ("request", request), ("context", "\n".join(context)),
                       ("step_shape", shape.strip())):
        text = text.replace("{{" + key + "}}", value)

    directory = project.tasks_dir / f"{num:03d}-{task_type}-{slug}"
    directory.mkdir(parents=True, exist_ok=False)
    write_atomic(directory / TASK_FILE, text)
    return Task(num, task_type, slug, directory), warnings


VIOLATIONS_HEADING = "## Violations"


def record_violation(task: Task, line: str) -> None:
    """Append `- <line>` to the Violations section, creating it at the end if needed."""
    text = task.text()
    entry = f"- {line}\n"
    start = text.find(f"\n{VIOLATIONS_HEADING}\n")
    if start == -1:
        text = text.rstrip("\n") + f"\n\n{VIOLATIONS_HEADING}\n{entry}"
    else:
        following = text.find("\n## ", start + 1)
        insert_at = len(text) if following == -1 else following + 1
        before = text[:insert_at].rstrip("\n") + "\n"
        text = before + entry + ("\n" + text[insert_at:] if following != -1 else "")
    write_atomic(task.path, text)


def work_plan_gates(task: Task) -> list[gates.Gate]:
    return [g for g in task.gates() if g.section.startswith("3.")]


def task_for_path(project: Project, rel_path: str) -> str | None:
    """The task directory name when `rel_path` is a task.md, else None."""
    match = TASK_PATH_RE.search(rel_path)
    return match.group(2) if match else None
