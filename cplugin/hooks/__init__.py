"""Hook handlers, keyed by the event name hooks/run.py receives."""

from __future__ import annotations

from pathlib import Path

from . import session_start

HANDLERS = {
    "session-start": session_start.handle,
}


def dispatch(event: str, payload: dict, plugin_root: Path) -> dict | None:
    handler = HANDLERS.get(event)
    if handler is None:
        raise ValueError(f"unknown hook event {event!r}")
    return handler(payload, plugin_root)
