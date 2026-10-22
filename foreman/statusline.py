"""The status line under the prompt, and a foreman line below it in a foreman project.

    Opus 5.5 [xhigh] · 45k/1M · 5h 12% · 8.12M (↑3.02M ↓5.10M) · $1.23
    foreman · task 003 shout · gate 7/18 · worker ● Edit src/combat.ts

Claude Code runs .claude/bin/statusline with the session's JSON on stdin and
shows what it prints. The first line is a port of a bash + jq script the user
wrote with a colleague; the second reads the records the board reads. Nothing
here raises: a figure that cannot be read is left out.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import board, gates, session, status
from .project import Project, find_project_root

RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"
GREEN, YELLOW, RED, CYAN, MAGENTA = "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[36m", "\x1b[35m"
BRIGHT_CYAN, BRIGHT_BLUE, BRIGHT_MAGENTA = "\x1b[96m", "\x1b[94m", "\x1b[95m"

# Token weights, roughly the pricing ratios: cache writes and reads against plain input, output.
CACHE_WRITE_WEIGHT, CACHE_READ_WEIGHT, OUTPUT_WEIGHT = 1.25, 0.1, 5
DEFAULT_WINDOW = 200_000
DETAIL_WIDTH = 40


@dataclass(frozen=True)
class Weighted:
    input: float = 0
    output: float = 0

    @property
    def total(self) -> float:
        return self.input + self.output


def _paint(text: str, *codes: str, color: bool) -> str:
    return f"{''.join(codes)}{text}{RESET}" if color and codes else text


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _get(data: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def format_tokens(count: float) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.2f}M"
    if count >= 1000:
        return f"{count / 1000:.0f}k"
    return str(int(count))


def format_window(size: float) -> str:
    if size >= 1_000_000:
        return f"{int(size // 1_000_000)}M" if size % 1_000_000 == 0 else f"{size / 1_000_000:.1f}M"
    if size >= 1000:
        return f"{int(size // 1000)}k"
    return str(int(size))


def format_percent(value: float) -> str:
    return f"{round(value, 1):g}%"


def short_model(name: str) -> str:
    return re.sub(r" \([^()]*context\)$", "", name)


def _usage_by_message(path: Path) -> dict[str, dict]:
    """The usage of each model response in one transcript. A response is written
    as several lines repeating its usage, the early ones with a partial output
    count, so the last line of each message wins."""
    found: dict[str, dict] = {}
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for number, line in enumerate(fh):
                if '"usage"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                message = entry.get("message") if isinstance(entry, dict) else None
                usage = message.get("usage") if isinstance(message, dict) else None
                if isinstance(usage, dict):
                    key = message.get("id") or entry.get("uuid") or f"line-{number}"
                    found[str(key)] = usage
    except OSError:
        pass
    return found


def transcripts(main: Path) -> list[Path]:
    """The session's transcript and its sub-agents' (<session>/subagents/agent-*.jsonl)."""
    return [main, *sorted((main.parent / main.stem / "subagents").glob("agent-*.jsonl"))]


def weighted_usage(transcript: Path) -> Weighted:
    weighted_in = weighted_out = 0.0
    for path in transcripts(transcript):
        for usage in _usage_by_message(path).values():
            weighted_in += ((_number(usage.get("input_tokens")) or 0)
                            + CACHE_WRITE_WEIGHT * (_number(usage.get("cache_creation_input_tokens")) or 0)
                            + CACHE_READ_WEIGHT * (_number(usage.get("cache_read_input_tokens")) or 0))
            weighted_out += OUTPUT_WEIGHT * (_number(usage.get("output_tokens")) or 0)
    return Weighted(round(weighted_in), round(weighted_out))


def _context_color(percent: float) -> str:
    return GREEN if percent < 50 else YELLOW if percent < 80 else RED


def _rate_color(percent: float) -> str:
    return CYAN if percent < 50 else BRIGHT_BLUE if percent < 80 else BRIGHT_MAGENTA


def _effort_color(level: str) -> str:
    return {"max": BRIGHT_MAGENTA, "xhigh": BRIGHT_MAGENTA, "high": YELLOW}.get(level, DIM)


def session_line(data: dict, color: bool) -> str:
    """Model and effort · context · five-hour limit · weighted tokens · cost."""
    sep = _paint("·", DIM, color=color)
    model = _get(data, "model", "display_name") or _get(data, "model", "id") or "unknown"
    head = _paint(short_model(str(model)), BOLD, BRIGHT_CYAN, color=color)
    effort = _get(data, "effort", "level")
    if isinstance(effort, str) and effort:
        head += (" " + _paint("[", DIM, color=color) + _paint(effort, _effort_color(effort), color=color)
                 + _paint("]", DIM, color=color))
    parts = [head]

    window = _number(_get(data, "context_window", "context_window_size")) or DEFAULT_WINDOW
    used = _number(_get(data, "context_window", "total_input_tokens")) or 0
    percent = _number(_get(data, "context_window", "used_percentage")) or 0
    parts.append(_paint(format_tokens(used), _context_color(percent), color=color)
                 + _paint(f"/{format_window(window)}", DIM, color=color))

    five_hour = _number(_get(data, "rate_limits", "five_hour", "used_percentage"))
    if five_hour is not None:
        parts.append(_paint("5h", DIM, color=color) + " "
                     + _paint(format_percent(five_hour), _rate_color(five_hour), color=color))

    transcript = _get(data, "transcript_path")
    tokens = weighted_usage(Path(transcript)) if isinstance(transcript, str) and transcript else Weighted()
    parts.append(_paint(format_tokens(tokens.total), BOLD, YELLOW, color=color) + " "
                 + _paint("(", DIM, color=color)
                 + _paint(f"↑{format_tokens(tokens.input)}", BRIGHT_BLUE, color=color) + " "
                 + _paint(f"↓{format_tokens(tokens.output)}", BRIGHT_MAGENTA, color=color)
                 + _paint(")", DIM, color=color))

    cost = _number(_get(data, "cost", "total_cost_usd")) or 0
    parts.append(_paint(f"${cost:.2f}", BOLD, MAGENTA, color=color))
    return f" {sep} ".join(parts)


def _fit(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def foreman_line(data: dict, color: bool) -> str | None:
    """The active task and gate, freehand or a pause, and the sub-agents working
    now. None outside a foreman project."""
    start = _get(data, "workspace", "project_dir") or _get(data, "cwd")
    root = find_project_root(start) if isinstance(start, str) and start else None
    if root is None:
        return None
    project = Project(root)
    session_id = session.safe_session_id(data.get("session_id"))
    state = session.read_state(session.session_dir(project, session_id)) if session_id else {}
    task = status.active_task(project, session_id)

    sep = _paint("·", DIM, color=color)
    parts = [_paint("foreman", BOLD, color=color)]
    if state.get("freehand"):
        parts.append(_paint("freehand: rules off", YELLOW, color=color))
    if task is not None:
        done, total = gates.progress(task.gates())
        parts.append(f"task {task.label} {task.slug}")
        parts.append(f"gate {min(done + 1, total)}/{total}" if done < total else "every gate checked")
    elif not state.get("freehand"):
        parts.append(_paint("no active task", DIM, color=color))
    if state.get("pause"):
        parts.append(_paint(f"waiting for you: {_fit(str(state['pause']), DETAIL_WIDTH)}", YELLOW, color=color))
    for row in board.collect(project, session_id).rows:
        if row.active and row.name != "MAIN":
            detail = f" {_fit(row.detail, DETAIL_WIDTH)}" if row.detail else ""
            parts.append(f"{row.name} {_paint(board.ACTIVE, GREEN, color=color)} {row.status}{detail}")
    return f" {sep} ".join(parts)


def render(stdin_text: str, color: bool = True) -> str:
    """Both lines for the JSON Claude Code sent; whatever cannot be read is left out."""
    try:
        data = json.loads(stdin_text) if stdin_text.strip() else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    lines = []
    for build in (session_line, foreman_line):
        try:
            line = build(data, color)
        except Exception:  # a status line must never fail; the other line still shows
            line = None
        if line:
            lines.append(line)
    return "\n".join(lines)
