"""Hook handlers, keyed by the event name hooks/run.py receives."""

from __future__ import annotations

from pathlib import Path

from . import post_tool_use, pre_tool_use, session_end, session_start, stop, subagent

HANDLERS = {
    "session-start": session_start.handle,
    "pre-tool-use": pre_tool_use.handle,
    "post-tool-use": post_tool_use.handle,
    "subagent-start": subagent.handle_start,
    "subagent-stop": subagent.handle_stop,
    "stop": stop.handle,
    "session-end": session_end.handle,
}


def dispatch(event: str, payload: dict, plugin_root: Path) -> dict | None:
    handler = HANDLERS.get(event)
    if handler is None:
        raise ValueError(f"unknown hook event {event!r}")
    return handler(payload, plugin_root)
