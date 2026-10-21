"""Single entry point for every cplugin hook: run.py <event>.

Reads the hook payload from stdin and prints the handler's JSON reply. A hook
must never take the session down, so any internal error is reported on stderr
and the hook exits 0.
"""

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str]) -> int:
    event = argv[1] if len(argv) > 1 else ""
    if sys.version_info < (3, 11):
        print(f"cplugin: needs Python 3.11+, found {sys.version.split()[0]}; hook {event} skipped",
              file=sys.stderr)
        return 0
    sys.path.insert(0, str(PLUGIN_ROOT))
    try:
        from cplugin.hooks import dispatch

        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        result = dispatch(event, payload, PLUGIN_ROOT)
    except Exception as exc:
        print(f"cplugin: {event or '?'} hook failed: {exc!r}", file=sys.stderr)
        return 0
    if result is not None:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
