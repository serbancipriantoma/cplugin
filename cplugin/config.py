"""Reading .cplugin/config.toml, with defaults for everything left out."""

from __future__ import annotations

import copy
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
}


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
