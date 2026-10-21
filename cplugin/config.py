"""Reading .cplugin/config.toml, with defaults for everything left out."""

from __future__ import annotations

import copy
import shutil
import tomllib

from .project import Project

DEFAULT_CODE_EXTENSIONS = [
    # web and mobile
    "js", "jsx", "mjs", "cjs", "ts", "tsx", "mts", "cts", "vue", "svelte", "astro",
    "html", "htm", "css", "scss", "sass", "less", "dart", "swift", "kt", "kts", "java",
    # games and shaders
    "gd", "gdshader", "glsl", "wgsl", "hlsl", "shader", "cs",
    # general purpose
    "py", "pyi", "go", "rs", "rb", "php", "lua", "c", "cc", "cpp", "cxx", "h", "hpp",
    "m", "mm", "scala", "zig", "ex", "exs", "erl", "ml", "mli", "clj", "r", "sql",
    "sh", "bash", "zsh", "ps1", "tf", "hcl",
]

DEFAULTS: dict = {
    "workflow": {"tests_first": True},
    "files": {
        "code_extensions": DEFAULT_CODE_EXTENSIONS,
        "extra_code_extensions": [],
        "code_dirs": ["bin", "scripts"],
    },
    "tests": {"command": ""},
    "roles": {
        "main": {"paths": ["MIND_MAP.md", "mindmap/**"]},
        "worker": {"model": "opus", "paths": ["**"], "max_parallel": 1},
        "tester": {"model": "sonnet", "paths": ["tests/**", "test/**", "**/__tests__/**",
                                                "**/test_*.py", "**/*_test.*", "**/*.test.*",
                                                "**/*.spec.*"]},
    },
    "judges": {"mode": "panel", "timeout_min": 15, "fallback": "claude", "seat": []},
}

MODEL_ALIASES = ("opus", "sonnet", "haiku", "fable")
JUDGE_COMMANDS = {"codex": "codex", "agy": "agy", "antigravity": "agy"}


class ConfigError(Exception):
    pass


def _merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load(project: Project) -> dict:
    try:
        with open(project.config_path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        data = {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{project.config_path}: {exc}") from exc
    return _merge(DEFAULTS, data)


def load_or_defaults(project: Project, warnings: list[str] | None = None) -> dict:
    """For hooks: a broken config must not stop enforcement, so fall back to defaults."""
    try:
        return load(project)
    except ConfigError as exc:
        if warnings is not None:
            warnings.append(f"config ignored, using defaults: {exc}")
        return copy.deepcopy(DEFAULTS)


def code_extensions(cfg: dict) -> set[str]:
    files = cfg.get("files", {})
    exts = list(files.get("code_extensions", [])) + list(files.get("extra_code_extensions", []))
    return {str(e).lower().lstrip(".") for e in exts}


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def check(cfg: dict) -> list[tuple[str, str]]:
    """Problems in a loaded config, as (ERROR|WARNING, message)."""
    found: list[tuple[str, str]] = []
    if not isinstance(cfg.get("workflow", {}).get("tests_first"), bool):
        found.append(("ERROR", "workflow.tests_first must be true or false"))
    for role in ("main", "worker", "tester"):
        section = cfg.get("roles", {}).get(role, {})
        paths = section.get("paths")
        if not _is_str_list(paths):
            found.append(("ERROR", f"roles.{role}.paths must be a list of glob strings"))
        elif not paths and role != "main":
            found.append(("WARNING", f"roles.{role}.paths is empty: the {role} cannot write anything"))
        model = section.get("model")
        if role != "main" and model not in MODEL_ALIASES:
            found.append(("WARNING", f"roles.{role}.model is {model!r}; the Agent tool only takes "
                                     f"{', '.join(MODEL_ALIASES)}, so it cannot be enforced"))
    for key in ("code_extensions", "extra_code_extensions", "code_dirs"):
        if not _is_str_list(cfg.get("files", {}).get(key)):
            found.append(("ERROR", f"files.{key} must be a list of strings"))
    command = str(cfg.get("tests", {}).get("command") or "").strip()
    if not command:
        found.append(("WARNING", "tests.command is empty: set the project's test command, e.g. \"npm test\""))
    elif shutil.which(command.split()[0]) is None:
        found.append(("WARNING", f"tests.command starts with {command.split()[0]!r}, which is not on PATH"))
    seats = cfg.get("judges", {}).get("seat", [])
    for seat in seats if isinstance(seats, list) else []:
        provider = str(seat.get("provider", "")) if isinstance(seat, dict) else ""
        executable = JUDGE_COMMANDS.get(provider)
        if executable is None:
            found.append(("WARNING", f"judge provider {provider!r} is not supported (use codex or agy)"))
        elif shutil.which(executable) is None:
            found.append(("WARNING", f"judge provider {provider!r}: `{executable}` is not on PATH"))
    return found
