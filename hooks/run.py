"""Single entry point for every foreman hook: run.py <event>.

Reads the hook payload from stdin and prints the handler's JSON reply. A hook
must never take the session down, so any internal error is reported on stderr
and the hook exits 0.

Set FOREMAN_HOOK_LOG to a file path to append every payload and reply to it
(one JSON object per line), for debugging.
"""

import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _log(event: str, payload: object, result: object) -> None:
    path = os.environ.get("FOREMAN_HOOK_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": event, "payload": payload, "result": result}) + "\n")
    except OSError:
        pass


def main(argv: list[str]) -> int:
    event = argv[1] if len(argv) > 1 else ""
    if os.environ.get("FOREMAN_JUDGE"):
        return 0  # a judge's own Claude session: no workflow to enforce there
    if sys.version_info < (3, 11):
        print(f"foreman: needs Python 3.11+, found {sys.version.split()[0]}; hook {event} skipped",
              file=sys.stderr)
        return 0
    sys.path.insert(0, str(PLUGIN_ROOT))
    payload: object = None
    try:
        from foreman.hooks import dispatch

        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        result = dispatch(event, payload, PLUGIN_ROOT)
    except Exception as exc:
        print(f"foreman: {event or '?'} hook failed: {exc!r}", file=sys.stderr)
        _log(event, payload, {"error": repr(exc)})
        return 0
    _log(event, payload, result)
    if result is not None:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
