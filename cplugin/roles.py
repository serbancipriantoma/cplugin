"""Who may write what while a task is active.

MAIN (the main session) owns the active task.md and the mind map; the worker
owns production code; the tester owns tests. Files that are neither code nor
MAIN's are open to every role. Any other sub-agent (Explore, general-purpose,
...) owns nothing.
"""

from __future__ import annotations

from pathlib import Path

from . import codefiles, globs

PLUGIN_PREFIX = "cplugin:"
MAIN, WORKER, TESTER, OTHER = "main", "worker", "tester", "other"
UNASSIGNED = "unassigned"   # code matched by neither the tester nor the worker paths
WORKFLOW_HINT = "See the cplugin:workflow skill for how to delegate a step."


def role_of(payload: dict) -> str:
    agent_type = payload.get("agent_type")
    if not agent_type:
        return MAIN
    if agent_type.startswith(PLUGIN_PREFIX):
        name = agent_type[len(PLUGIN_PREFIX):]
        if name in (WORKER, TESTER):
            return name
    return OTHER


def role_paths(cfg: dict, role: str) -> list[str]:
    paths = cfg.get("roles", {}).get(role, {}).get("paths", [])
    return [str(p) for p in paths] if isinstance(paths, list) else []


def owner(rel: str, abs_path: Path, cfg: dict) -> str | None:
    """The role that owns `rel`, or None when every role may write it."""
    if globs.matches(rel, role_paths(cfg, MAIN)):
        return MAIN
    if not codefiles.is_code_file(rel, abs_path, cfg):
        return None
    if globs.matches(rel, role_paths(cfg, TESTER)):
        return TESTER
    if globs.matches(rel, role_paths(cfg, WORKER)):
        return WORKER
    return UNASSIGNED


def write_violation(role: str, rel: str, abs_path: Path, cfg: dict) -> str | None:
    """Why `role` may not write `rel`, or None when it may."""
    own = owner(rel, abs_path, cfg)
    if own is None or own == role:
        return None
    if own == UNASSIGNED:
        return (f"{rel} is code, but it matches neither roles.worker.paths nor roles.tester.paths "
                f"in .cplugin/config.toml, so no role may write it. If it should be writable, "
                f"the main agent adds it to the right role's paths.")
    if role == MAIN:
        what = "tests" if own == TESTER else "production code"
        return (f"The main agent coordinates and does not write {what}: {rel} belongs to the "
                f"{own}. Delegate the change with the Agent tool, subagent_type "
                f"'cplugin:{own}'. {WORKFLOW_HINT}")
    if own == MAIN:
        return (f"{rel} belongs to the main agent. Put what you have to say about it in your "
                f"final report instead.")
    if role == WORKER:
        return (f"As the worker you may not change tests: {rel} belongs to the tester. If a test "
                f"looks wrong, say which one and why in your report; the main agent decides.")
    if role == TESTER:
        return (f"As the tester you may not change production code: {rel} belongs to the worker. "
                f"Test the interface you were given, and report if it cannot be tested as specified.")
    return (f"While a task is active only cplugin:worker writes code and only cplugin:tester "
            f"writes tests; {rel} belongs to the {own}. Report back to the main agent instead.")
